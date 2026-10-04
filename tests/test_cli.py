import json
import subprocess
import sys
import textwrap

import matplotlib
import pytest
from PIL import Image

from mpl_inspector.cli import main

GOOD = """
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.plot([1, 2, 3], [1, 4, 9])
ax.set(title="squares", xlabel="n", ylabel="n^2")
plt.show()
"""

BAD = """
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(4, 3))
ax.bar([f"category number {i}" for i in range(8)], range(1, 9))
ax.set(title="t", xlabel="x", ylabel="y")
"""


@pytest.fixture
def script(tmp_path):
    def write(source, name="plot.py"):
        path = tmp_path / name
        path.write_text(textwrap.dedent(source))
        return path

    return write


def report(tmp_path, name="plot"):
    return json.loads((tmp_path / "out" / f"{name}.json").read_text())


def test_clean_script_exits_zero(script, tmp_path, capsys):
    code = main([str(script(GOOD)), "-o", str(tmp_path / "out")])
    assert code == 0
    data = report(tmp_path)
    assert data["status"] == "ok"
    assert data["summary"] == {"error": 0, "warning": 0, "info": 0}
    assert (tmp_path / "out" / "plot-fig0.png").stat().st_size > 0
    assert data["figures"][0]["snapshot"]["axes"][0]["title"] == "squares"
    assert "report:" in capsys.readouterr().out


def test_errors_exit_one_and_print_fix(script, tmp_path, capsys):
    code = main([str(script(BAD)), "-o", str(tmp_path / "out")])
    out = capsys.readouterr().out
    assert code == 1
    assert "[error] fig0 ax0.xticklabels tick-label-overlap" in out
    assert "fix: " in out
    assert report(tmp_path)["figures"][0]["diagnostics"][0]["code"] == "tick-label-overlap"


@pytest.mark.parametrize(("fail_on", "expected"), [("never", 0), ("error", 0), ("warning", 0), ("info", 1)])
def test_fail_on(script, tmp_path, fail_on, expected):
    source = GOOD.replace('ax.set(title="squares", ', "ax.set(")  # only missing-title (info)
    assert main([str(script(source)), "-o", str(tmp_path / "out"), "--fail-on", fail_on]) == expected


def test_script_error_exits_two_and_keeps_figures(script, tmp_path):
    path = script(GOOD.replace("plt.show()", "1 / 0"))
    assert main([str(path), "-o", str(tmp_path / "out")]) == 2
    data = report(tmp_path)
    assert data["status"] == "script-error"
    assert "ZeroDivisionError" in data["error"]
    assert data["diagnostics"][0]["code"] == "script-error"
    assert len(data["figures"]) == 1


def test_no_figures_exits_two(script, tmp_path):
    assert main([str(script("x = 1\n")), "-o", str(tmp_path / "out")]) == 2
    assert report(tmp_path)["diagnostics"][0]["code"] == "no-figures"


def test_captures_closed_saved_and_oo_figures(script, tmp_path):
    source = f"""
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    fig, ax = plt.subplots()
    ax.plot([1, 2])
    fig.savefig({str(tmp_path / 'a.png')!r})
    plt.close(fig)
    oo = Figure()
    oo.add_subplot().plot([2, 1])
    oo.savefig({str(tmp_path / 'b.png')!r})
    """
    main([str(script(source)), "-o", str(tmp_path / "out"), "--fail-on", "never"])
    assert len(report(tmp_path)["figures"]) == 2


def test_script_args_and_backend_pinned(script, tmp_path):
    source = """
    import sys
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    ax.plot([1, 2])
    ax.set(title=sys.argv[1], xlabel="x", ylabel="y")
    assert matplotlib.get_backend().lower() == "agg"
    """
    code = main([str(script(source)), "-o", str(tmp_path / "out"), "--", "from-argv"])
    assert code == 0
    assert report(tmp_path)["figures"][0]["snapshot"]["axes"][0]["title"] == "from-argv"


def test_json_flag(script, tmp_path, capsys):
    main([str(script(GOOD)), "-o", str(tmp_path / "out"), "--json"])
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_python_dash_m(script, tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "mpl_inspector", str(script(BAD)), "-o", str(tmp_path / "out")],
        capture_output=True,
        text=True,
        env={"PATH": "", "MPLBACKEND": "TkAgg"},
    )
    assert result.returncode == 1, result.stderr
    assert "tick-label-overlap" in result.stdout


def test_png_ignores_script_savefig_bbox(script, tmp_path):
    source = """
    import matplotlib.pyplot as plt
    plt.rcParams["savefig.bbox"] = "tight"
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot([1, 2])
    """
    with matplotlib.rc_context():
        main([str(script(source)), "-o", str(tmp_path / "out"), "--fail-on", "never"])
    entry = report(tmp_path)["figures"][0]
    with Image.open(entry["png"]) as png:
        assert list(png.size) == entry["snapshot"]["size_px"]


def test_layout_warning_reported_once(script, tmp_path):
    source = f"""
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(4, 4, figsize=(1, 1), layout="tight")
    for ax in axes.flat:
        ax.set(title="a very long title", xlabel="a long x label", ylabel="a long y label")
    fig.savefig({str(tmp_path / 'a.png')!r})
    """
    main([str(script(source)), "-o", str(tmp_path / "out"), "--fail-on", "never"])
    data = report(tmp_path)
    everything = data["diagnostics"] + data["figures"][0]["diagnostics"]
    assert [d["code"] for d in everything].count("layout-warning") == 1
    assert data["summary"]["warning"] == sum(d["severity"] == "warning" for d in everything)
