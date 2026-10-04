"""``mpl-axi``: agent-ergonomic client for the live inspection protocol.

Attach to a process that called ``mpl_inspector.serve()`` (or one started with
``mpl-axi launch script.py``), then inspect, modify and re-render its figures
without rerunning the script. Output is compact TOON with a ``help`` list of
next commands; ``--json`` prints the raw protocol result instead.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from . import toon
from .live import Client, RpcError, sessions_dir

USAGE = """usage: mpl-axi [command] [args] [--json]
commands:
  (none)                      home: session, figures, next steps
  sessions                    list live sessions
  attach <pid>                choose the session other commands talk to
  launch <script> [-- args]   run a script headlessly and serve its figures
  figures                     list figures
  tree [@f]                   figure > axes > artists with refs
  get <@ref|id>               properties of one object
  set <@ref|id> k=v ...       change properties and re-render (values are JSON or text)
  invoke <@ref> <method> [arg ...] [k=v ...]  call a public method, e.g. invoke @x1 tick_params axis=x labelrotation=45
  screenshot [@ref] [path]    PNG of a figure or one element
  highlight <@ref> | --clear  outline an element (shows in screenshots)
  lint [@f]                   diagnostics with refs and fixes
  snapshot [@f] [path]        full JSON snapshot to a file
  events [--count N] [--timeout S]  wait for draw/resize/change events
  call <Domain.method> [json] raw protocol call
  stop                        shut the session down"""


class AxiError(Exception):
    def __init__(self, code: str, message: str, help: list[str]) -> None:
        super().__init__(message)
        self.code = code
        self.help = help


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if argv and argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    command, args = (argv[0], argv[1:]) if argv else ("home", [])
    handler = COMMANDS.get(command)
    try:
        if handler is None:
            raise AxiError("UNKNOWN_COMMAND", f"unknown command {command!r}", ["Run `mpl-axi --help` to list commands"])
        data, raw, help = handler(args)
    except AxiError as exc:
        _print({"error": str(exc), "code": exc.code}, exc.help, as_json)
        return 1
    except RpcError as exc:
        _print({"error": str(exc), "code": exc.code}, _recover(exc.code), as_json)
        return 1
    except (ConnectionError, OSError) as exc:
        _print({"error": f"session unreachable: {exc}", "code": "UNREACHABLE"}, ["Run `mpl-axi sessions` to see live sessions"], as_json)
        return 1
    except (ValueError, TypeError) as exc:
        _print({"error": f"{type(exc).__name__}: {exc}", "code": "BAD_INPUT"}, ["Run `mpl-axi --help` for usage"], as_json)
        return 1
    if as_json:
        print(json.dumps(raw, indent=2))
    else:
        _print(data, help, False)
    return 0


def _print(data: dict[str, Any], help: list[str], as_json: bool) -> None:
    if as_json:
        print(json.dumps({**data, "help": help}, indent=2))
        return
    print(toon.dumps({**data, "help": help} if help else data))


def _recover(code: str) -> list[str]:
    if code == "NOT_FOUND":
        return ["Run `mpl-axi tree` to get current refs"]
    if code == "NO_FIGURES":
        return ["Create a figure in the attached process, or `mpl-axi launch <script>`"]
    return ["Run `mpl-axi --help` for usage"]


# --------------------------------------------------------------------------- sessions


def _sessions() -> list[dict[str, Any]]:
    found = []
    for path in sorted(sessions_dir().glob("*.json")):
        try:
            info = json.loads(path.read_text())
            os.kill(int(info["pid"]), 0)
        except (OSError, ValueError, KeyError):
            path.unlink(missing_ok=True)  # stale: process is gone
            continue
        found.append(info)
    return found


def _current(required: bool = True) -> dict[str, Any] | None:
    sessions = _sessions()
    wanted = os.environ.get("MPL_AXI_SESSION")
    marker = sessions_dir() / "current"
    if wanted is None and marker.exists():
        wanted = marker.read_text().strip()
    match = [s for s in sessions if str(s["pid"]) == str(wanted)] if wanted else []
    if match:
        return match[0]
    if len(sessions) == 1:
        return sessions[0]
    if not required:
        return None
    if not sessions:
        raise AxiError("NO_SESSION", "no live session", [
            "Run `mpl-axi launch <script.py>` to start one",
            "Or call `mpl_inspector.serve()` in your Python process/notebook",
        ])
    raise AxiError("MULTIPLE_SESSIONS", f"{len(sessions)} live sessions; choose one", ["Run `mpl-axi sessions` then `mpl-axi attach <pid>`"])


def _client() -> Client:
    return Client(_current()["url"])


def _call(method: str, /, **params: Any) -> Any:
    client = _client()
    try:
        return client.call(method, **params)
    finally:
        client.close()


def _figure_arg(args: list[str]) -> str | None:
    return next((a for a in args if a.startswith("@f")), None)


def _target(args: list[str], usage: str) -> str:
    if not args:
        raise AxiError("MISSING_ARG", f"missing element ref; usage: {usage}", ["Run `mpl-axi tree` to list refs"])
    return args[0]


# --------------------------------------------------------------------------- commands
# Each returns (toon data, raw result for --json, help lines).

Result = tuple[dict[str, Any], Any, list[str]]


def cmd_home(args: list[str]) -> Result:
    data: dict[str, Any] = {"bin": "mpl-axi", "description": "Inspect and edit live Matplotlib figures over the mpl_inspector protocol"}
    session = _current(required=False)
    if session is None:
        count = len(_sessions())
        data["session"] = None if count == 0 else f"{count} live, none attached"
        help = ["Run `mpl-axi launch <script.py>` to run a script and serve its figures"] if count == 0 else ["Run `mpl-axi sessions` then `mpl-axi attach <pid>`"]
        return data, data, help
    client = Client(session["url"])
    try:
        info = client.call("Session.info")
        figures = client.call("Figure.list")
    finally:
        client.close()
    data["session"] = {"pid": info["pid"], "backend": info["backend"], "script": info["script"] or "-"}
    if info["script_error"]:
        data["session"]["script_error"] = info["script_error"].strip().splitlines()[-1]
    data["figures"] = [_figure_row(f) for f in figures]
    help = ["Run `mpl-axi tree` to list artists with refs", "Run `mpl-axi lint` to find problems"] if figures else ["Create a figure in the attached process"]
    return data, {"session": info, "figures": figures}, help


def cmd_sessions(args: list[str]) -> Result:
    current = _current(required=False)
    rows = [{"pid": s["pid"], "attached": current is not None and s["pid"] == current["pid"], "script": s.get("script") or "-", "url": s["url"]} for s in _sessions()]
    help = ["Run `mpl-axi attach <pid>` to choose one"] if rows else ["Run `mpl-axi launch <script.py>` to start one"]
    return {"sessions": rows}, rows, help


def cmd_attach(args: list[str]) -> Result:
    pid = _target(args, "mpl-axi attach <pid>")
    if not any(str(s["pid"]) == pid for s in _sessions()):
        raise AxiError("NOT_FOUND", f"no live session with pid {pid}", ["Run `mpl-axi sessions` to list them"])
    (sessions_dir() / "current").write_text(pid)
    return {"attached": int(pid)}, {"attached": int(pid)}, ["Run `mpl-axi` to see its figures"]


def cmd_launch(args: list[str]) -> Result:
    script = _target(args, "mpl-axi launch <script.py> [-- args]")
    extra = args[args.index("--") + 1 :] if "--" in args else args[1:]
    if not Path(script).exists():
        raise AxiError("NOT_FOUND", f"no such script {script}", ["Check the path"])
    log = sessions_dir() / f"launch-{int(time.time() * 1000)}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "w") as handle:
        proc = subprocess.Popen(
            [sys.executable, "-m", "mpl_inspector.live", script, *extra],
            stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
        )
    session_file = sessions_dir() / f"{proc.pid}.json"
    deadline = time.time() + 60
    while not session_file.exists():
        if proc.poll() is not None or time.time() > deadline:
            raise AxiError("LAUNCH_FAILED", f"script did not start a session; log: {log}", [f"Read {log}", "Run the script with `mpl-inspect` to see the error"])
        time.sleep(0.05)
    (sessions_dir() / "current").write_text(str(proc.pid))
    data, raw, help = cmd_home([])
    return data, raw, help + ["Run `mpl-axi stop` when done"]


def cmd_figures(args: list[str]) -> Result:
    figures = _call("Figure.list")
    return {"figures": [_figure_row(f) for f in figures]}, figures, ["Run `mpl-axi tree @f<N>` to list its artists"]


def cmd_tree(args: list[str]) -> Result:
    nodes = _call("Figure.getTree", figure=_figure_arg(args))
    rows = [{k: n[k] for k in ("ref", "parent", "id", "type", "call", "label", "visible")} for n in nodes]
    return {"nodes": rows}, nodes, ["Run `mpl-axi get @a<N>` for properties", "Run `mpl-axi set @a<N> color=red` to change one"]


def cmd_get(args: list[str]) -> Result:
    target = _target(args, "mpl-axi get <@ref>")
    result = _call("Artist.get", ref=target, figure=_figure_arg(args[1:]))
    data = {k: v for k, v in result.items() if k != "props"}
    data["props"] = result["props"]
    return data, result, [f"Run `mpl-axi set {result['ref']} <prop>=<value>` to change it", f"Run `mpl-axi screenshot {result['ref']}` to see it"]


def cmd_set(args: list[str]) -> Result:
    target = _target(args, "mpl-axi set <@ref> key=value ...")
    pairs = [a for a in args[1:] if "=" in a]
    if not pairs:
        raise AxiError("MISSING_ARG", "no key=value pairs given", [f"Run `mpl-axi get {target}` to see settable props"])
    props = {key: _value(value) for key, _, value in (pair.partition("=") for pair in pairs)}
    result = _call("Artist.set", ref=target, props=props, figure=_figure_arg([a for a in args[1:] if "=" not in a]))
    data = {"ref": result["ref"], "applied": result["applied"]}
    if result["errors"]:
        data["errors"] = result["errors"]
    data["props"] = {k: result["props"][k] for k in result["applied"] if k in result["props"]}
    help = [f"Run `mpl-axi screenshot {result['ref']}` to check the result", "Run `mpl-axi lint` to re-check the figure"]
    return data, result, help


def cmd_invoke(args: list[str]) -> Result:
    if len(args) < 2:
        raise AxiError("MISSING_ARG", "usage: mpl-axi invoke <@ref> <method> [arg ...] [k=v ...]", ["Run `mpl-axi tree` to list refs"])
    target, method, rest = args[0], args[1], args[2:]
    kwargs = {key: _value(value) for key, _, value in (a.partition("=") for a in rest if "=" in a)}
    positional = [_value(a) for a in rest if "=" not in a]
    result = _call("Artist.invoke", ref=target, method=method, args=positional, kwargs=kwargs)
    return result, result, ["Run `mpl-axi lint` to re-check the figure", "Run `mpl-axi screenshot` to view it"]


def _value(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def cmd_screenshot(args: list[str]) -> Result:
    ref = next((a for a in args if a.startswith("@") or "." in a and not a.endswith(".png")), None)
    path = next((a for a in args if a.endswith(".png")), None) or f"mpl-axi-{(ref or 'figure').lstrip('@').replace('.', '_')}.png"
    params: dict[str, Any] = {"path": path}
    if ref is not None and ref.startswith("@f"):
        params["figure"] = ref
    elif ref is not None:
        params["ref"] = ref
    result = _call("Figure.screenshot", **params)
    return result, result, [f"Open {result['path']} to view it"]


def cmd_highlight(args: list[str]) -> Result:
    if "--clear" in args:
        result = _call("Artist.clearHighlights", figure=_figure_arg(args))
        return result, result, ["Run `mpl-axi screenshot` to view the figure"]
    target = _target(args, "mpl-axi highlight <@ref> | --clear")
    result = _call("Artist.highlight", ref=target)
    return result, result, ["Run `mpl-axi screenshot` to see the outline", "Run `mpl-axi highlight --clear` to remove it"]


def cmd_lint(args: list[str]) -> Result:
    found = _call("Lint.run", figure=_figure_arg(args))
    rows = [{
        "severity": d["severity"], "code": d["code"], "ref": d["location"].get("ref"),
        "target": d["location"]["target"], "message": d["message"], "fix": d["fix"],
    } for d in found]
    counts = {s: sum(r["severity"] == s for r in rows) for s in ("error", "warning", "info")}
    help = [
        "Run `mpl-axi set <ref> <prop>=<value>` or `mpl-axi invoke <ref> <method> k=v` to apply a fix",
        "Run `mpl-axi lint` again to confirm",
    ] if rows else ["Run `mpl-axi screenshot` to view the figure"]
    return {"summary": counts, "diagnostics": rows}, found, help


def cmd_snapshot(args: list[str]) -> Result:
    figure = _figure_arg(args)
    path = next((a for a in args if a.endswith(".json")), None) or "mpl-axi-snapshot.json"
    result = _call("Figure.snapshot", figure=figure)
    Path(path).write_text(json.dumps(result, indent=2))
    data = {"path": str(Path(path).resolve()), "axes": len(result["axes"]), "artists": sum(len(a["artists"]) for a in result["axes"])}
    return data, result, [f"Read {path} for the full schema (see AGENT.md)"]


def cmd_events(args: list[str]) -> Result:
    count = int(_option(args, "--count", "1"))
    timeout = float(_option(args, "--timeout", "10"))
    client = _client()
    try:
        client.call("Events.subscribe")
        client.sock.settimeout(timeout)
        deadline = time.time() + timeout
        while len(client.events) < count and time.time() < deadline:
            try:
                client.next_message()  # notifications land in client.events
            except (TimeoutError, OSError):
                break
        events = client.events[:count]
    finally:
        client.close()
    rows = [{"event": e["method"].removeprefix("Events."), **{k: e["params"].get(k) for k in ("figure", "ref", "what")}} for e in events]
    help = ["Run `mpl-axi events --count 5 --timeout 30` to wait longer"] if not rows else ["Run `mpl-axi screenshot` to view the current state"]
    return {"events": rows}, events, help


def cmd_call(args: list[str]) -> Result:
    method = _target(args, "mpl-axi call <Domain.method> [json-params]")
    params = json.loads(args[1]) if len(args) > 1 else {}
    result = _call(method, **params)
    data = result if isinstance(result, dict) else {"result": result}
    return data, result, ["Run `mpl-axi call Session.methods` to list methods"]


def cmd_stop(args: list[str]) -> Result:
    result = _call("Session.shutdown")
    (sessions_dir() / "current").unlink(missing_ok=True)
    return result, result, ["Run `mpl-axi launch <script.py>` to start another session"]


def _option(args: list[str], name: str, default: str) -> str:
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def _figure_row(figure: dict[str, Any]) -> dict[str, Any]:
    width, height = figure["size_px"]
    return {"ref": figure["ref"], "title": figure["title"], "size": f"{width}x{height}", "axes": figure["axes"], "artists": figure["artists"]}


COMMANDS: dict[str, Callable[[list[str]], Result]] = {
    "home": cmd_home,
    "sessions": cmd_sessions,
    "attach": cmd_attach,
    "launch": cmd_launch,
    "figures": cmd_figures,
    "tree": cmd_tree,
    "get": cmd_get,
    "set": cmd_set,
    "invoke": cmd_invoke,
    "screenshot": cmd_screenshot,
    "highlight": cmd_highlight,
    "lint": cmd_lint,
    "snapshot": cmd_snapshot,
    "events": cmd_events,
    "call": cmd_call,
    "stop": cmd_stop,
}


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
