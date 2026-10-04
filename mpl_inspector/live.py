"""CDP-style live inspection protocol for running Matplotlib processes.

Opt in from any Python process or notebook::

    import mpl_inspector
    server = mpl_inspector.serve()      # ws://127.0.0.1:<port>/<token>

or run a script and keep its figures alive for an agent::

    python -m mpl_inspector.live plot.py [script args]

The server speaks JSON-RPC 2.0 over a WebSocket bound to 127.0.0.1 only.
The URL carries a random token; it is written, with the pid, to a session
file (mode 0600) in ``$MPL_INSPECTOR_SESSIONS`` (default
``~/.cache/mpl_inspector/sessions``) so ``mpl-axi`` can discover it.

Domains (``method`` = ``Domain.name``): Session, Figure, Artist, Lint, Events.
See AGENT.md for every method and its params. Objects are addressed by stable
refs: ``@f1`` (figure), ``@x1`` (axes), ``@a1`` (any other artist).
"""

from __future__ import annotations

import atexit
import base64
import hashlib
import io
import json
import os
import platform
import secrets
import socket
import struct
import sys
import tempfile
import threading
import time
import traceback
import weakref
from pathlib import Path
from typing import Any, Callable

import matplotlib
from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.legend import Legend
from matplotlib.text import Text
from matplotlib.transforms import Bbox

from .highlight import HighlightStyle, create_highlight
from .lint import _sup_texts, lint
from .provenance import infer_call
from .snapshot import _bbox, _extent, _hex, _num, get_renderer, iter_axes_artists, root_figure, snapshot

PROTOCOL_VERSION = "1"
_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_LOCK = threading.RLock()  # ponytail: one global lock; Matplotlib is not thread-safe anyway


class RpcError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- refs


class _Refs:
    """Stable short refs (``f1``, ``x2``, ``a3``) for live Matplotlib objects."""

    def __init__(self) -> None:
        self._objects: dict[str, weakref.ref] = {}
        self._by_id: dict[int, str] = {}
        self._counters = {"f": 0, "x": 0, "a": 0}

    def ref(self, obj: Any) -> str:
        known = self._by_id.get(id(obj))
        if known is not None and self._objects[known]() is obj:
            return "@" + known
        kind = "f" if isinstance(obj, Figure) else "x" if isinstance(obj, Axes) else "a"
        self._counters[kind] += 1
        key = f"{kind}{self._counters[kind]}"
        self._objects[key] = weakref.ref(obj)
        self._by_id[id(obj)] = key
        return "@" + key

    def get(self, ref: str) -> Any:
        holder = self._objects.get(str(ref).lstrip("@"))
        obj = holder() if holder is not None else None
        if obj is None:
            raise RpcError("NOT_FOUND", f"no live object for ref {ref}; refresh refs with Figure.getTree")
        return obj


# --------------------------------------------------------------------------- server


class LiveServer:
    """WebSocket JSON-RPC server exposing this process's figures."""

    def __init__(self, port: int = 0, *, session_dir: str | os.PathLike[str] | None = None, script: str | None = None) -> None:
        self.token = secrets.token_urlsafe(16)
        self.refs = _Refs()
        self.script = script
        self.script_error: str | None = None
        self._figures: list[weakref.ref] = []
        self._connected: set[int] = set()
        self._highlights: dict[int, list[Any]] = {}
        self._subscribers: dict[Any, set[str]] = {}
        self._stopped = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", port))
        self._sock.listen()
        self.port = self._sock.getsockname()[1]
        self.url = f"ws://127.0.0.1:{self.port}/{self.token}"
        self.session_file = Path(session_dir or sessions_dir()) / f"{os.getpid()}.json"
        self._write_session_file()
        self._thread = threading.Thread(target=self._accept_loop, name="mpl-inspector-live", daemon=True)
        self._thread.start()
        atexit.register(self.stop)

    # -- lifecycle -------------------------------------------------------

    def track(self, fig: Figure) -> None:
        with _LOCK:
            if not any(known() is fig for known in self._figures):
                self._figures.append(weakref.ref(fig))

    def stop(self) -> None:
        if self._stopped.is_set():
            return
        self._stopped.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self.session_file.unlink(missing_ok=True)
        global _SERVER
        if _SERVER is self:
            _SERVER = None

    def wait(self) -> None:
        """Block until ``Session.shutdown`` (or ``stop()``)."""
        self._stopped.wait()

    def _write_session_file(self) -> None:
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        info = {"pid": os.getpid(), "url": self.url, "port": self.port, "script": self.script, "started": int(time.time())}
        fd, tmp = tempfile.mkstemp(dir=self.session_file.parent, prefix=".session-", suffix=".tmp")
        with os.fdopen(fd, "w") as handle:
            json.dump(info, handle)
        os.replace(tmp, self.session_file)

    # -- transport -------------------------------------------------------

    def _accept_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve_connection, args=(conn,), daemon=True).start()

    def _serve_connection(self, conn: socket.socket) -> None:
        peer = _Peer(conn)
        try:
            if not _server_handshake(conn, self.token):
                return
            while not self._stopped.is_set():
                message = peer.recv()
                if message is None:
                    return
                peer.send(json.dumps(self.handle(message, peer)))
        except (OSError, ConnectionError, ValueError):
            return
        finally:
            with _LOCK:
                self._subscribers.pop(peer, None)
            conn.close()

    def handle(self, raw: str, peer: Any = None) -> dict[str, Any]:
        """Answer one JSON-RPC request (also usable without a socket, e.g. in tests)."""
        request_id = None
        try:
            request = json.loads(raw)
            request_id = request.get("id")
            method = self._methods(peer).get(request.get("method", ""))
            if method is None:
                raise RpcError("UNKNOWN_METHOD", f"unknown method {request.get('method')!r}; see Session.methods")
            with _LOCK:
                result = method(**(request.get("params") or {}))
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcError as exc:
            return _error(request_id, exc.code, str(exc))
        except TypeError as exc:
            return _error(request_id, "BAD_PARAMS", str(exc))
        except json.JSONDecodeError as exc:
            return _error(request_id, "BAD_JSON", str(exc))
        except Exception as exc:  # noqa: BLE001 - report, keep serving
            return _error(request_id, "INTERNAL", f"{type(exc).__name__}: {exc}", traceback.format_exc())

    def _emit(self, event: str, params: dict[str, Any]) -> None:
        message = json.dumps({"jsonrpc": "2.0", "method": f"Events.{event}", "params": params})
        for peer, events in list(self._subscribers.items()):
            if event in events:
                try:
                    peer.send(message)
                except OSError:
                    self._subscribers.pop(peer, None)

    # -- object lookup ---------------------------------------------------

    def figures(self) -> list[Figure]:
        from matplotlib._pylab_helpers import Gcf

        alive = [fig for fig in (ref() for ref in self._figures) if fig is not None]
        for manager in Gcf.get_all_fig_managers():
            if not any(fig is manager.canvas.figure for fig in alive):
                alive.append(manager.canvas.figure)
        self._figures = [weakref.ref(fig) for fig in alive]
        for fig in alive:
            self._connect_figure(fig)
            for obj in self._targets(fig).values():  # deterministic refs in tree order
                self.refs.ref(obj)
        return alive

    def _figure(self, figure: str | None) -> Figure:
        if figure is None:
            figures = self.figures()
            if not figures:
                raise RpcError("NO_FIGURES", "this process has no open figures")
            return figures[-1]
        fig = self.refs.get(figure)
        if not isinstance(fig, Figure):
            raise RpcError("BAD_REF", f"{figure} is not a figure ref")
        return fig

    def _connect_figure(self, fig: Figure) -> None:
        ref = self.refs.ref(fig)
        if id(fig) in self._connected:
            return
        self._connected.add(id(fig))
        fig.canvas.mpl_connect("draw_event", lambda event: self._emit("draw", {"figure": ref}))
        fig.canvas.mpl_connect("resize_event", lambda event: self._emit("resize", {"figure": ref, "size_px": [event.width, event.height]}))

    def _targets(self, fig: Figure) -> dict[str, Artist]:
        """Snapshot/lint target ids (``ax0.3``, ``ax0.title`` ...) -> objects."""
        targets: dict[str, Artist] = {}
        for name in ("suptitle", "supxlabel", "supylabel"):
            text = getattr(fig, f"_{name}", None)
            if text is not None:
                targets[f"fig.{name}"] = text
        sup_texts = _sup_texts(fig)
        for index, text in enumerate(fig.texts):
            if text not in sup_texts:
                targets[f"fig.t{index}"] = text
        for ax_index, ax in enumerate(fig.axes):
            prefix = f"ax{ax_index}"
            targets[prefix] = ax
            targets[f"{prefix}.title"] = ax.title
            targets[f"{prefix}.xlabel"] = ax.xaxis.label
            targets[f"{prefix}.ylabel"] = ax.yaxis.label
            legend = ax.get_legend()
            if isinstance(legend, Legend):
                targets[f"{prefix}.legend"] = legend
            for index, artist in enumerate(iter_axes_artists(ax)):
                targets[f"{prefix}.{index}"] = artist
        return targets

    def _resolve(self, ref: str, figure: str | None = None) -> Any:
        """Accept a ref (``@a3``) or a snapshot id (``ax0.3``) on *figure*."""
        if str(ref).startswith("@"):
            try:
                return self.refs.get(ref)
            except RpcError:
                self.figures()  # assign refs to anything created since the last walk
                return self.refs.get(ref)
        obj = self._targets(self._figure(figure)).get(ref)
        if obj is None:
            raise RpcError("NOT_FOUND", f"no element {ref!r}; list them with Figure.getTree")
        return obj

    def _changed(self, fig: Figure, what: str, ref: str) -> None:
        fig.canvas.draw_idle()
        self._emit("change", {"figure": self.refs.ref(fig), "ref": ref, "what": what})

    # -- methods ---------------------------------------------------------

    def _methods(self, peer: Any = None) -> dict[str, Callable[..., Any]]:
        return {
            "Session.info": self._session_info,
            "Session.methods": lambda: sorted(self._methods()),
            "Session.shutdown": self._session_shutdown,
            "Figure.list": self._figure_list,
            "Figure.getTree": self._figure_tree,
            "Figure.snapshot": lambda figure=None: snapshot(self._figure(figure)),
            "Figure.screenshot": self._figure_screenshot,
            "Artist.get": self._artist_get,
            "Artist.set": self._artist_set,
            "Artist.highlight": self._artist_highlight,
            "Artist.clearHighlights": self._artist_clear,
            "Artist.invoke": self._artist_invoke,
            "Lint.run": self._lint_run,
            "Events.subscribe": lambda events=None: self._events_subscribe(peer, events),
            "Events.unsubscribe": lambda: self._events_unsubscribe(peer),
        }

    def _session_info(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL_VERSION,
            "pid": os.getpid(),
            "url": self.url,
            "python": platform.python_version(),
            "matplotlib": matplotlib.__version__,
            "backend": matplotlib.get_backend(),
            "script": self.script,
            "script_error": self.script_error,
            "figures": len(self.figures()),
        }

    def _session_shutdown(self) -> dict[str, Any]:
        threading.Timer(0.1, self.stop).start()  # let the reply go out first
        return {"stopping": True}

    def _figure_list(self) -> list[dict[str, Any]]:
        rows = []
        for fig in self.figures():
            suptitle = getattr(fig, "_suptitle", None)
            titles = [ax.get_title() for ax in fig.axes if ax.get_title()]
            rows.append({
                "ref": self.refs.ref(fig),
                "num": getattr(fig, "number", None),
                "title": suptitle.get_text() if suptitle is not None else (titles[0] if titles else ""),
                "size_px": [int(fig.bbox.width), int(fig.bbox.height)],
                "axes": len(fig.axes),
                "artists": sum(len(list(iter_axes_artists(ax))) for ax in fig.axes),
            })
        return rows

    def _figure_tree(self, figure: str | None = None) -> list[dict[str, Any]]:
        fig = self._figure(figure)
        nodes = [self._node(fig, None, "fig")]
        for target, obj in self._targets(fig).items():
            nodes.append(self._node(obj, self._parent(fig, target, obj), target))
        return nodes

    @staticmethod
    def _parent(fig: Figure, target: str, obj: Any) -> Any:
        if isinstance(obj, Axes) or not target.startswith("ax"):
            return fig
        return fig.axes[int(target[2:].split(".")[0])]

    def _node(self, obj: Any, parent: Any, target: str) -> dict[str, Any]:
        label = obj.get_text() if isinstance(obj, Text) else obj.get_label() if isinstance(obj, Artist) else ""
        return {
            "ref": self.refs.ref(obj),
            "parent": self.refs.ref(parent) if parent is not None else None,
            "id": target,
            "type": type(obj).__name__,
            "call": None if isinstance(obj, (Figure, Axes)) else infer_call(obj),
            "label": "" if (label or "").startswith("_") else label,
            "visible": obj.get_visible(),
        }

    def _figure_screenshot(self, figure: str | None = None, ref: str | None = None, path: str | None = None, padding: float = 8) -> dict[str, Any]:
        obj = self._resolve(ref, figure) if ref else self._figure(figure)
        fig = root_figure(obj)
        renderer = get_renderer(fig)
        crop = None
        if not isinstance(obj, Figure):
            box = _extent(obj, renderer)
            if box is None:
                raise RpcError("NO_EXTENT", f"{ref} has no on-screen extent (hidden or empty?)")
            box = Bbox.from_extents(box.x0 - padding, box.y0 - padding, box.x1 + padding, box.y1 + padding)
            crop = Bbox.intersection(box, fig.bbox)
            if crop is None:
                raise RpcError("NO_EXTENT", f"{ref} lies entirely outside the figure canvas")
        buffer = io.BytesIO()
        with matplotlib.rc_context({"savefig.bbox": "standard"}):
            bbox_inches = crop.transformed(fig.dpi_scale_trans.inverted()) if crop is not None else None
            fig.savefig(buffer, format="png", dpi=fig.dpi, bbox_inches=bbox_inches, pad_inches=0)
        png = buffer.getvalue()
        width, height = struct.unpack(">II", png[16:24])
        result: dict[str, Any] = {"ref": self.refs.ref(obj), "width": width, "height": height, "bbox_display": _bbox(crop or fig.bbox)}
        if path:
            Path(path).write_bytes(png)
            result["path"] = str(Path(path).resolve())
        else:
            result["data"] = base64.b64encode(png).decode()
        return result

    def _artist_get(self, ref: str, figure: str | None = None) -> dict[str, Any]:
        obj = self._resolve(ref, figure)
        if isinstance(obj, Figure):
            record = {k: v for k, v in snapshot(obj).items() if k not in ("axes", "texts", "legends")}
        else:
            fig = root_figure(obj)
            renderer = get_renderer(fig)
            box = _extent(obj, renderer) if not isinstance(obj, Axes) else obj.get_window_extent(renderer)
            record = {"type": type(obj).__name__, "call": None if isinstance(obj, Axes) else infer_call(obj), "bbox_display": _bbox(box)}
        record = {"ref": self.refs.ref(obj), **record, "props": _props(obj)}
        return record

    def _artist_set(self, ref: str, props: dict[str, Any], figure: str | None = None) -> dict[str, Any]:
        obj = self._resolve(ref, figure)
        applied, errors = [], {}
        for name, value in props.items():
            try:
                obj.set(**{name: value})
                applied.append(name)
            except Exception as exc:  # noqa: BLE001 - report per property
                errors[name] = f"{type(exc).__name__}: {exc}"
        fig = root_figure(obj)
        if applied:
            self._changed(fig, "set", self.refs.ref(obj))
        return {"ref": self.refs.ref(obj), "applied": applied, "errors": errors, "props": _props(obj)}

    def _artist_invoke(self, ref: str, method: str, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None, figure: str | None = None) -> dict[str, Any]:
        """Call a public method, e.g. ``tick_params`` on an axes or ``set_layout_engine`` on a figure."""
        obj = self._resolve(ref, figure)
        if method.startswith("_") or not callable(getattr(obj, method, None)):
            raise RpcError("BAD_METHOD", f"{type(obj).__name__} has no public method {method!r}")
        value = getattr(obj, method)(*(args or []), **(kwargs or {}))
        self._changed(root_figure(obj), method, self.refs.ref(obj))
        return {"ref": self.refs.ref(obj), "method": method, "returned": self._returned(value)}

    def _returned(self, value: Any) -> Any:
        if isinstance(value, (Artist, Figure)):
            return self.refs.ref(value)
        if isinstance(value, (list, tuple)) and value and all(isinstance(v, Artist) for v in value):
            return [self.refs.ref(v) for v in value]
        return _json_value("", value)

    def _artist_highlight(self, ref: str, color: str = "#ff00ff", figure: str | None = None) -> dict[str, Any]:
        obj = self._resolve(ref, figure)
        if isinstance(obj, Figure):
            raise RpcError("BAD_REF", "highlight an axes or artist, not a figure")
        fig = root_figure(obj)
        handle = create_highlight(obj, style=HighlightStyle(color=color), renderer=get_renderer(fig))
        if handle is None:
            raise RpcError("NO_EXTENT", f"cannot highlight {ref}")
        self._highlights.setdefault(id(fig), []).append(handle)
        self._changed(fig, "highlight", self.refs.ref(obj))
        return {"ref": self.refs.ref(obj), "highlights": len(self._highlights[id(fig)])}

    def _artist_clear(self, figure: str | None = None) -> dict[str, Any]:
        fig = self._figure(figure)
        handles = self._highlights.pop(id(fig), [])
        for handle in handles:
            handle.remove()
        self._changed(fig, "clearHighlights", self.refs.ref(fig))
        return {"figure": self.refs.ref(fig), "cleared": len(handles)}

    def _lint_run(self, figure: str | None = None, min_fontsize: float | None = None) -> list[dict[str, Any]]:
        fig = self._figure(figure)
        found = lint(fig) if min_fontsize is None else lint(fig, min_fontsize=min_fontsize)
        targets = self._targets(fig)
        for diag in found:
            target = diag["location"]["target"]
            obj = targets.get(target) if target else None
            if obj is None and target and target.startswith("ax"):  # e.g. ax0.xticklabels -> its axes
                obj = targets.get(target.split(".")[0])
            diag["location"]["ref"] = self.refs.ref(obj) if obj is not None else None
        return found

    def _events_subscribe(self, peer: Any, events: list[str] | None) -> dict[str, Any]:
        if peer is None:
            raise RpcError("NO_CONNECTION", "Events need a WebSocket connection")
        wanted = set(events or ("draw", "resize", "change"))
        self._subscribers.setdefault(peer, set()).update(wanted)
        self.figures()  # hook draw/resize on every current figure
        return {"events": sorted(self._subscribers[peer])}

    def _events_unsubscribe(self, peer: Any) -> dict[str, Any]:
        self._subscribers.pop(peer, None)
        return {"events": []}


_PROPS = (
    "label", "visible", "alpha", "zorder", "color", "facecolor", "edgecolor", "linewidth", "linestyle",
    "marker", "markersize", "text", "fontsize", "fontweight", "rotation", "position", "cmap", "clim",
    "title", "xlabel", "ylabel", "xlim", "ylim", "xscale", "yscale",
)


def _props(obj: Any) -> dict[str, Any]:
    """Common settable properties, JSON-safe (keys can be passed back to Artist.set)."""
    props: dict[str, Any] = {}
    for name in _PROPS:
        getter = getattr(obj, f"get_{name}", None)
        if getter is None or (name == "label" and isinstance(obj, Axes)):
            continue
        try:
            value = getter()
        except Exception:  # noqa: BLE001 - some getters need state the object lacks
            continue
        props[name] = _json_value(name, value)
    return props


def _json_value(name: str, value: Any) -> Any:
    if name in ("color", "facecolor", "edgecolor"):
        return _hex(value)
    if name == "cmap":
        return getattr(value, "name", str(value))
    if isinstance(value, (str, bool, int)) or value is None:
        return value
    if isinstance(value, float):
        return _num(value)
    if isinstance(value, (tuple, list)) and all(isinstance(v, (int, float)) for v in value):
        return [_num(v) for v in value]
    return str(value)


def _error(request_id: Any, code: str, message: str, trace: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"code": code}
    if trace:
        data["traceback"] = trace
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": message, "data": data}}


# --------------------------------------------------------------------------- websocket (RFC 6455, minimal)


def _server_handshake(conn: socket.socket, token: str) -> bool:
    request = _read_http(conn)
    first, *headers = request.split("\r\n")
    fields = {k.strip().lower(): v.strip() for k, _, v in (h.partition(":") for h in headers if ":" in h)}
    parts = first.split()
    if len(parts) < 2 or parts[1] != f"/{token}" or "sec-websocket-key" not in fields:
        conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        return False
    accept = base64.b64encode(hashlib.sha1((fields["sec-websocket-key"] + _GUID).encode()).digest()).decode()
    conn.sendall(
        "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n".encode()
    )
    return True


def _read_http(conn: socket.socket) -> str:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk or len(data) > 65536:
            raise ConnectionError("bad handshake")
        data += chunk
    return data.split(b"\r\n\r\n", 1)[0].decode("latin-1")


class _Peer:
    """One WebSocket endpoint. Text frames only; no fragmentation or extensions."""

    def __init__(self, conn: socket.socket, *, mask: bool = False) -> None:
        self.conn = conn
        self.mask = mask  # clients must mask, servers must not
        self._send_lock = threading.Lock()
        self._buffer = b""

    def send(self, text: str, opcode: int = 1) -> None:
        payload = text.encode()
        header = bytes([0x80 | opcode])
        mask_bit = 0x80 if self.mask else 0
        size = len(payload)
        if size < 126:
            header += bytes([mask_bit | size])
        elif size < 65536:
            header += bytes([mask_bit | 126]) + struct.pack(">H", size)
        else:
            header += bytes([mask_bit | 127]) + struct.pack(">Q", size)
        if self.mask:
            key = secrets.token_bytes(4)
            payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
            header += key
        with self._send_lock:
            self.conn.sendall(header + payload)

    def recv(self) -> str | None:
        while True:
            first, second = self._read(2)
            opcode, masked, size = first & 0x0F, second & 0x80, second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._read(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._read(8))[0]
            key = self._read(4) if masked else b""
            payload = self._read(size)
            if masked:
                payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
            if opcode == 8:
                return None
            if opcode == 9:
                self.send(payload.decode("latin-1"), opcode=10)
                continue
            if opcode == 1:
                return payload.decode()

    def _read(self, size: int) -> bytes:
        while len(self._buffer) < size:
            chunk = self.conn.recv(max(65536, size - len(self._buffer)))
            if not chunk:
                raise ConnectionError("connection closed")
            self._buffer += chunk
        data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data


class Client:
    """Minimal JSON-RPC client: ``Client(url).call("Figure.list")``."""

    def __init__(self, url: str, timeout: float = 30.0) -> None:
        rest = url.removeprefix("ws://")
        address, _, path = rest.partition("/")
        host, _, port = address.partition(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        self.sock.sendall(
            f"GET /{path} HTTP/1.1\r\nHost: {address}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        if " 101 " not in _read_http(self.sock).split("\r\n", 1)[0] + " ":
            raise ConnectionError("handshake refused (wrong or stale session token?)")
        self.peer = _Peer(self.sock, mask=True)
        self._next_id = 0
        self.events: list[dict[str, Any]] = []

    def call(self, method: str, /, **params: Any) -> Any:
        self._next_id += 1
        self.peer.send(json.dumps({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}))
        while True:
            message = self.next_message()
            if message.get("id") == self._next_id:
                if "error" in message:
                    error = message["error"]
                    raise RpcError(error.get("data", {}).get("code", "ERROR"), error.get("message", ""))
                return message["result"]

    def next_message(self) -> dict[str, Any]:
        text = self.peer.recv()
        if text is None:
            raise ConnectionError("server closed the connection")
        message = json.loads(text)
        if "id" not in message:
            self.events.append(message)
        return message

    def close(self) -> None:
        try:
            self.peer.send("", opcode=8)
        except OSError:
            pass
        self.sock.close()


# --------------------------------------------------------------------------- entry points

_SERVER: LiveServer | None = None


def sessions_dir() -> Path:
    return Path(os.environ.get("MPL_INSPECTOR_SESSIONS") or Path.home() / ".cache" / "mpl_inspector" / "sessions")


def serve(fig: Figure | None = None, *, port: int = 0) -> LiveServer:
    """Start (or reuse) this process's live server and track *fig* if given.

    Every pyplot figure is visible automatically; pass non-pyplot figures
    (``Figure()``) explicitly. Opt-in only: nothing listens until you call this.
    """
    from matplotlib._pylab_helpers import Gcf

    global _SERVER
    if _SERVER is None:
        _SERVER = LiveServer(port)
    _track_pyplot_figures()
    for manager in Gcf.get_all_fig_managers():
        _SERVER.track(manager.canvas.figure)
    if fig is not None:
        _SERVER.track(fig)
    return _SERVER


def _track_pyplot_figures() -> None:
    """Remember (by weakref) every pyplot figure made active, so figures that
    the inline notebook backend closes after each cell stay inspectable."""
    from matplotlib._pylab_helpers import Gcf

    set_active = Gcf.set_active.__func__
    if getattr(set_active, "_mpl_inspector", False):
        return

    def tracking_set_active(cls: Any, manager: Any) -> None:
        set_active(cls, manager)
        if _SERVER is not None:
            _SERVER.track(manager.canvas.figure)

    tracking_set_active._mpl_inspector = True  # type: ignore[attr-defined]
    Gcf.set_active = classmethod(tracking_set_active)  # type: ignore[method-assign]


def main(argv: list[str] | None = None) -> int:
    """``python -m mpl_inspector.live script.py [args]``: run headlessly, then serve until shutdown."""
    import runpy

    from .cli import _capture_figures, _open_figures, _remember, script_traceback

    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: python -m mpl_inspector.live script.py [script args]", file=sys.stderr)
        return 2
    os.environ["MPLBACKEND"] = "Agg"
    matplotlib.use("Agg", force=True)
    path = Path(argv[0]).resolve()
    figures: list[Any] = []
    error = None
    with _capture_figures(figures):
        old_argv = sys.argv
        sys.argv = [str(path), *argv[1:]]
        sys.path.insert(0, str(path.parent))
        try:
            runpy.run_path(str(path), run_name="__main__")
        except SystemExit as exc:
            if exc.code not in (None, 0):
                error = f"SystemExit: {exc.code}"
        except Exception as exc:  # noqa: BLE001 - keep serving whatever was drawn
            error = script_traceback(exc, path)
        finally:
            sys.argv = old_argv
        _remember(figures, *_open_figures())
    server = serve()  # reuses the server if the script already called serve()
    server.script, server.script_error = str(path), error
    server._write_session_file()
    for fig in figures:
        server.track(fig)
    print(json.dumps({"url": server.url, "pid": os.getpid(), "figures": len(figures), "script_error": error}), flush=True)
    server.wait()
    return 0


if __name__ == "__main__":  # pragma: no cover
    from mpl_inspector.live import main as _main  # run in the package module so serve() sees one server

    sys.exit(_main())
