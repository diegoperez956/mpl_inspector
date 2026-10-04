import base64
import gc
import json
import os
import socket
import stat
import time

import matplotlib.pyplot as plt
import pytest
from matplotlib.figure import Figure

from mpl_inspector import toon
from mpl_inspector.live import Client, LiveServer, RpcError, serve


@pytest.fixture
def server(tmp_path):
    srv = LiveServer(session_dir=tmp_path)
    yield srv
    srv.stop()
    plt.close("all")


@pytest.fixture
def client(server):
    c = Client(server.url, timeout=10)
    yield c
    c.close()


@pytest.fixture
def fig(server):
    figure, ax = plt.subplots()
    ax.plot([1, 2, 3], [1, 4, 9], label="squares")
    ax.set_title("T")
    ax.legend()
    return figure


def node(client, target):
    return next(n for n in client.call("Figure.getTree") if n["id"] == target)


def test_session_file_is_private_and_removed(server):
    info = json.loads(server.session_file.read_text())
    assert info["pid"] == os.getpid()
    assert info["url"] == server.url
    assert info["url"].startswith("ws://127.0.0.1:")
    assert stat.S_IMODE(server.session_file.stat().st_mode) == 0o600
    server.stop()
    assert not server.session_file.exists()


def test_wrong_token_is_refused(server):
    with pytest.raises(ConnectionError):
        Client(server.url.rsplit("/", 1)[0] + "/wrong")


def test_binds_localhost_only(server):
    assert server._sock.getsockname()[0] == "127.0.0.1"


def test_info_and_methods(client, fig):
    info = client.call("Session.info")
    assert info["protocol"] == "1"
    assert info["figures"] == 1
    methods = client.call("Session.methods")
    assert {"Figure.getTree", "Artist.set", "Lint.run", "Events.subscribe", "Artist.invoke"} <= set(methods)


def test_figure_list_and_deterministic_refs(client, fig):
    assert client.call("Figure.list") == [
        {"ref": "@f1", "num": fig.number, "title": "T", "size_px": [640, 480], "axes": 1, "artists": 1}
    ]
    tree = client.call("Figure.getTree")
    assert [(n["ref"], n["id"], n["parent"]) for n in tree] == [
        ("@f1", "fig", None),
        ("@x1", "ax0", "@f1"),
        ("@a1", "ax0.title", "@x1"),
        ("@a2", "ax0.xlabel", "@x1"),
        ("@a3", "ax0.ylabel", "@x1"),
        ("@a4", "ax0.legend", "@x1"),
        ("@a5", "ax0.0", "@x1"),
    ]
    assert client.call("Figure.getTree") == tree  # stable across calls


def test_refs_resolve_before_tree(client, fig):
    assert client.call("Artist.get", ref="@a5")["type"] == "Line2D"


def test_get_by_ref_or_snapshot_id(client, fig):
    by_ref = client.call("Artist.get", ref="@a5")
    by_id = client.call("Artist.get", ref="ax0.0")
    assert by_ref == by_id
    assert by_ref["call"] == "ax.plot()"
    assert by_ref["props"]["label"] == "squares"
    assert by_ref["props"]["color"] == "#1f77b4"


def test_set_rerenders_and_emits_events(client, fig):
    assert client.call("Events.subscribe") == {"events": ["change", "draw", "resize"]}
    result = client.call("Artist.set", ref="@a5", props={"color": "red", "linewidth": 4, "nope": 1})
    assert result["applied"] == ["color", "linewidth"]
    assert "nope" in result["errors"]
    assert result["props"]["color"] == "#ff0000"
    assert fig.axes[0].lines[0].get_linewidth() == 4
    events = {e["method"] for e in client.events}
    assert {"Events.draw", "Events.change"} <= events
    change = next(e for e in client.events if e["method"] == "Events.change")
    assert change["params"] == {"figure": "@f1", "ref": "@a5", "what": "set"}


def test_set_title_text(client, fig):
    client.call("Artist.set", ref="ax0.title", props={"text": "New", "fontsize": 20})
    assert fig.axes[0].get_title() == "New"
    assert fig.axes[0].title.get_fontsize() == 20


def test_invoke_public_method_fixes_lint(client):
    figure, ax = plt.subplots(figsize=(4, 3))
    ax.bar([f"category number {i}" for i in range(8)], range(1, 9))
    ax.set(title="t", xlabel="x", ylabel="y")
    found = client.call("Lint.run")
    overlap = next(d for d in found if d["code"] == "tick-label-overlap")
    assert overlap["location"]["ref"] == "@x1"  # tick labels map to their axes
    client.call("Artist.invoke", ref="@x1", method="tick_params", kwargs={"axis": "x", "labelrotation": 90})
    client.call("Artist.invoke", ref="@f1", method="set_layout_engine", args=["constrained"])
    codes = {d["code"] for d in client.call("Lint.run")}
    assert not codes & {"tick-label-overlap", "text-cut-off"}


def test_invoke_rejects_private(client, fig):
    with pytest.raises(RpcError) as err:
        client.call("Artist.invoke", ref="@x1", method="_get_lines")
    assert err.value.code == "BAD_METHOD"


def test_screenshot_figure_and_element(client, fig, tmp_path):
    whole = client.call("Figure.screenshot")
    png = base64.b64decode(whole["data"])
    assert png.startswith(b"\x89PNG")
    assert (whole["width"], whole["height"]) == (640, 480)
    path = tmp_path / "title.png"
    part = client.call("Figure.screenshot", ref="@a1", path=str(path))
    assert path.read_bytes().startswith(b"\x89PNG")
    assert part["width"] < 200 and part["height"] < 60


def test_highlight_and_clear(client, fig):
    before = len(fig.axes[0].get_children())
    assert client.call("Artist.highlight", ref="@a5")["highlights"] == 1
    assert len(fig.axes[0].get_children()) > before
    assert client.call("Artist.clearHighlights") == {"figure": "@f1", "cleared": 1}
    assert len(fig.axes[0].get_children()) == before


def test_snapshot_and_lint(client, fig):
    assert client.call("Figure.snapshot")["axes"][0]["title"] == "T"
    found = client.call("Lint.run")
    label = next(d for d in found if d["location"]["target"] == "ax0.xlabel")
    assert label["location"]["ref"] == "@a2"


def test_non_pyplot_figure_needs_tracking(server, client):
    figure = Figure()
    figure.add_subplot().plot([1, 2])
    with pytest.raises(RpcError):
        client.call("Figure.getTree")
    server.track(figure)
    assert client.call("Figure.list")[0]["axes"] == 1


def test_closed_pyplot_figures_drop_out_unless_served_explicitly(tmp_path, monkeypatch):
    monkeypatch.setenv("MPL_INSPECTOR_SESSIONS", str(tmp_path))
    server = serve()
    client = Client(server.url, timeout=10)
    try:
        discarded, _ = plt.subplots()
        kept, ax = plt.subplots()
        ax.plot([1, 2])
        serve(kept)
        plt.close("all")  # what the inline notebook backend does after each cell
        assert [f["axes"] for f in client.call("Figure.list")] == [1]
    finally:
        client.close()
        server.stop()


def test_served_figures_survive_gc_without_other_references(server, client):
    standalone = Figure()
    standalone.add_subplot().set_title("standalone")
    server.track(standalone)
    closed, ax = plt.subplots()
    ax.set_title("closed")
    server.track(closed)
    plt.close(closed)
    del standalone, closed, ax
    gc.collect()
    assert [f["title"] for f in client.call("Figure.list")] == ["standalone", "closed"]


def test_closed_figure_refs_are_not_found(client, fig):
    assert client.call("Figure.list")[0]["ref"] == "@f1"
    plt.close(fig)
    for method, params in [("Figure.getTree", {"figure": "@f1"}), ("Figure.snapshot", {"figure": "@f1"}), ("Artist.get", {"ref": "@a1"})]:
        with pytest.raises(RpcError) as err:
            client.call(method, **params)
        assert err.value.code == "NOT_FOUND", method


def test_open_figures_keep_creation_order_and_default_is_last(server, client):
    a, ax_a = plt.subplots()
    ax_a.set_title("A")
    b, ax_b = plt.subplots()
    ax_b.set_title("B")
    server.track(b)
    rows = client.call("Figure.list")
    assert [r["title"] for r in rows] == ["A", "B"]
    assert client.call("Figure.getTree")[0]["ref"] == rows[-1]["ref"]


def test_snapshot_text_ids_all_resolve(client, fig):
    fig.suptitle("Big")
    fig.supxlabel("time")
    fig.supylabel("value")
    fig.text(0.5, 0.5, "note")
    ids = [t["id"] for t in client.call("Figure.snapshot")["texts"]]
    assert ids == ["fig.suptitle", "fig.supxlabel", "fig.supylabel", "fig.t3"]
    for target in ids:
        assert client.call("Artist.get", ref=target)["type"] == "Text"


def test_session_file_is_replaced_atomically(server, tmp_path):
    server.script = "plot.py"
    server._write_session_file()
    assert json.loads(server.session_file.read_text())["script"] == "plot.py"
    assert stat.S_IMODE(server.session_file.stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == [server.session_file.name]


def test_suptitle_appears_once_in_tree(client, fig):
    fig.suptitle("Big")
    fig.supxlabel("time")
    nodes = [n for n in client.call("Figure.getTree") if n["type"] == "Text" and n["parent"] == "@f1"]
    assert [n["id"] for n in nodes] == ["fig.suptitle", "fig.supxlabel"]
    assert len({n["ref"] for n in nodes}) == 2
    assert node(client, "fig.supxlabel")["ref"].startswith("@a")


def test_screenshot_of_offcanvas_element_is_refused(client, fig):
    fig.text(1.5, 0.5, "gone")
    with pytest.raises(RpcError) as err:
        client.call("Figure.screenshot", ref="fig.t0")
    assert err.value.code == "NO_EXTENT"


def test_errors_are_coded(client, fig):
    for method, params, code in [
        ("Nope.x", {}, "UNKNOWN_METHOD"),
        ("Artist.get", {"ref": "@a999"}, "NOT_FOUND"),
        ("Artist.get", {"ref": "ax9.9"}, "NOT_FOUND"),
        ("Artist.get", {}, "BAD_PARAMS"),
        ("Figure.getTree", {"figure": "@a5"}, "BAD_REF"),
    ]:
        with pytest.raises(RpcError) as err:
            client.call(method, **params)
        assert err.value.code == code, method


def test_shutdown(server, client):
    assert client.call("Session.shutdown") == {"stopping": True}
    deadline = time.time() + 5
    while server.session_file.exists() and time.time() < deadline:
        time.sleep(0.02)
    assert not server.session_file.exists()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", server.port), timeout=1).recv(1)


def test_large_message_roundtrip(client, fig):
    fig.axes[0].set_title("x" * 70000)
    assert len(client.call("Artist.get", ref="@a1")["props"]["text"]) == 70000


def test_toon_encoding():
    text = toon.dumps({
        "a": 1,
        "b": "plain text",
        "c": "needs, quoting",
        "d": {"x": None, "y": True},
        "rows": [{"ref": "@a1", "v": 1.5}, {"ref": "@a2", "v": "1"}],
        "short": ["@a1", "@a2"],
        "help": ["Run `x` to do y"],
        "empty": [],
    })
    assert text.splitlines() == [
        "a: 1",
        "b: plain text",
        'c: "needs, quoting"',
        "d:",
        "  x: null",
        "  y: true",
        "rows[2]{ref,v}:",
        "  @a1,1.5",
        '  @a2,"1"',
        "short[2]: @a1,@a2",
        "help[1]:",
        "  Run `x` to do y",
        "empty[0]:",
    ]
