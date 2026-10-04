import json
import os
import signal
import subprocess
import textwrap

import pytest

from mpl_inspector.axi import main

SCRIPT = """
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(4, 3))
ax.bar([f"category number {i}" for i in range(8)], range(1, 9))
ax.set(title="Revenue", xlabel="region", ylabel="USD")
"""


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("MPL_INSPECTOR_SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.delenv("MPL_AXI_SESSION", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path / "sessions"


@pytest.fixture
def launched(sessions, tmp_path, capsys):
    script = tmp_path / "plot.py"
    script.write_text(textwrap.dedent(SCRIPT))
    assert main(["launch", str(script)]) == 0
    capsys.readouterr()
    pid = int((sessions / "current").read_text())
    yield pid
    try:
        main(["stop"])
    finally:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().out


def test_home_without_session(sessions, capsys):
    code, out = run(capsys)
    assert code == 0
    assert "session: null" in out
    assert "help[1]:\n  Run `mpl-axi launch <script.py>`" in out


def test_unreadable_session_kept_dead_session_removed(sessions, capsys):
    sessions.mkdir(parents=True)
    partial = sessions / "1.json"
    partial.write_text("")  # a session file caught mid-write
    proc = subprocess.Popen(["true"])
    proc.wait()
    dead = sessions / f"{proc.pid}.json"
    dead.write_text(json.dumps({"pid": proc.pid, "url": "ws://127.0.0.1:1/x"}))
    code, out = run(capsys, "sessions")
    assert code == 0
    assert partial.exists()
    assert not dead.exists()


def test_errors_are_terse_with_recovery(sessions, capsys):
    code, out = run(capsys, "tree")
    assert code == 1
    assert out.splitlines()[:2] == ["error: no live session", "code: NO_SESSION"]
    assert "help[2]:" in out
    code, out = run(capsys, "frobnicate")
    assert code == 1 and "code: UNKNOWN_COMMAND" in out


def test_home_tree_get_set(launched, capsys):
    code, out = run(capsys)
    assert code == 0
    assert "figures[1]{ref,title,size,axes,artists}:\n  @f1,Revenue,400x300,1,8" in out
    assert out.rstrip().splitlines()[-1].startswith("  Run `mpl-axi")

    code, out = run(capsys, "tree")
    assert "nodes[" in out and "  @x1,@f1,ax0,Axes," in out and "  @a1,@x1,ax0.title,Text,ax.set_title(),Revenue,true" in out

    code, out = run(capsys, "set", "@a1", "fontsize=20", "color=red", "text=Sales by region")
    assert code == 0
    assert "applied[3]: fontsize,color,text" in out
    code, out = run(capsys, "get", "@a1", "--json")
    props = json.loads(out)["props"]
    assert (props["fontsize"], props["color"], props["text"]) == (20, "#ff0000", "Sales by region")


def test_lint_invoke_loop(launched, capsys):
    code, out = run(capsys, "lint")
    assert "  error,tick-label-overlap,@x1,ax0.xticklabels," in out
    assert run(capsys, "invoke", "@x1", "tick_params", "axis=x", "labelrotation=90")[0] == 0
    assert run(capsys, "invoke", "@f1", "set_layout_engine", "constrained")[0] == 0
    code, out = run(capsys, "lint")
    assert "summary:\n  error: 0" in out


def test_screenshot_snapshot_events(launched, capsys, tmp_path):
    code, out = run(capsys, "screenshot", "@a1", "title.png")
    assert code == 0 and (tmp_path / "title.png").read_bytes().startswith(b"\x89PNG")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.chdir(elsewhere)
    code, out = run(capsys, "screenshot", "@a1", "rel.png")
    assert code == 0 and (elsewhere / "rel.png").exists() and not (tmp_path / "rel.png").exists()
    os.chdir(tmp_path)
    code, out = run(capsys, "snapshot")
    assert json.loads((tmp_path / "mpl-axi-snapshot.json").read_text())["axes"][0]["title"] == "Revenue"
    code, out = run(capsys, "events", "--count", "1", "--timeout", "0.5")
    assert code == 0 and "events[0]:" in out


def test_sessions_attach_stop(launched, sessions, capsys):
    code, out = run(capsys, "sessions")
    assert f"  {launched},true," in out
    assert run(capsys, "attach", str(launched))[0] == 0
    assert run(capsys, "attach", "1")[0] == 1
    code, out = run(capsys, "stop")
    assert "stopping: true" in out


def test_launch_hides_figures_the_script_closed(sessions, tmp_path, capsys):
    script = tmp_path / "batch.py"
    script.write_text(textwrap.dedent("""
        import matplotlib.pyplot as plt
        for n in range(3):
            fig, ax = plt.subplots()
            ax.set_title(f"saved {n}")
            fig.savefig(f"out{n}.png")
            plt.close(fig)
        fig, ax = plt.subplots()
        ax.set_title("kept")
    """))
    assert main(["launch", str(script)]) == 0
    capsys.readouterr()
    try:
        for _ in range(2):
            code, out = run(capsys, "figures")
            assert code == 0 and "figures[1]" in out and "kept" in out and "saved" not in out
    finally:
        main(["stop"])


def test_launch_script_that_calls_serve(sessions, tmp_path, capsys):
    script = tmp_path / "served.py"
    script.write_text(textwrap.dedent(SCRIPT) + "import mpl_inspector\nmpl_inspector.serve()\n")
    assert main(["launch", str(script)]) == 0
    capsys.readouterr()
    try:
        code, out = run(capsys, "sessions")
        assert out.count(",true,") == 1 and "sessions[1]" in out
        code, out = run(capsys)
        assert "@f1,Revenue" in out
    finally:
        main(["stop"])
