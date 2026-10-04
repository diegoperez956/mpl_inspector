"""``mpl-inspect script.py``: run a plotting script headlessly and lint every figure.

Writes ``<out>/<script>.json`` (snapshot + diagnostics per figure) and one
``<out>/<script>-fig<N>.png`` per figure, prints one line per diagnostic and
exits with:

* ``0`` — no diagnostic at or above ``--fail-on`` (default: ``error``)
* ``1`` — at least one such diagnostic
* ``2`` — the script raised, or produced no figures
"""

from __future__ import annotations

import argparse
import json
import os
import runpy
import sys
import traceback
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import matplotlib

from .lint import CODES, MIN_FONTSIZE, SEVERITIES, lint, warning_diagnostics
from .snapshot import SCHEMA_VERSION, snapshot

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mpl-inspect",
        description="Run a Matplotlib script headlessly, save every figure as PNG + JSON, and lint it.",
        epilog="Pass arguments to the script after '--': mpl-inspect plot.py -o out -- --data a.csv",
    )
    parser.add_argument("script", help="path to the plotting script")
    parser.add_argument("-o", "--out", default="mpl-inspect-out", help="output directory (default: %(default)s)")
    parser.add_argument(
        "--fail-on",
        choices=[*SEVERITIES, "never"],
        default="error",
        help="lowest severity that makes the exit code 1 (default: %(default)s)",
    )
    parser.add_argument("--min-fontsize", type=float, default=MIN_FONTSIZE, help="smallest readable font size in pt")
    parser.add_argument("--json", action="store_true", help="print the full report JSON instead of the summary")
    argv = sys.argv[1:] if argv is None else argv
    script_args = argv[argv.index("--") + 1 :] if "--" in argv else []
    ns = parser.parse_args(argv[: argv.index("--")] if "--" in argv else argv)

    report = run(ns.script, script_args, out=ns.out, min_fontsize=ns.min_fontsize)
    if ns.json:
        print(json.dumps(report, indent=2))
    else:
        _print_summary(report)

    if report["status"] != "ok":
        return 2
    if ns.fail_on == "never":
        return 0
    worst = SEVERITIES.index(ns.fail_on)
    failing = sum(report["summary"][severity] for severity in SEVERITIES[: worst + 1])
    return 1 if failing else 0


def run(script: str, script_args: list[str] | None = None, *, out: str = "mpl-inspect-out", min_fontsize: float = MIN_FONTSIZE) -> dict[str, Any]:
    """Run *script* on the Agg backend and return (and write) the report dict."""
    os.environ["MPLBACKEND"] = "Agg"
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    path = Path(script).resolve()
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)

    figures: list[Any] = []
    error = None
    with _capture_figures(figures) as caught:
        old_argv, old_path = sys.argv, list(sys.path)
        sys.argv = [str(path), *(script_args or [])]
        sys.path.insert(0, str(path.parent))
        try:
            runpy.run_path(str(path), run_name="__main__")
        except SystemExit as exc:
            if exc.code not in (None, 0):
                error = f"SystemExit: {exc.code}"
        except Exception:  # noqa: BLE001 - report any crash; Ctrl-C still aborts
            error = traceback.format_exc()
        finally:
            sys.argv, sys.path[:] = old_argv, old_path
        _remember(figures, *_open_figures())

    diagnostics = warning_diagnostics(caught)
    if error is not None:
        last_line = error.strip().splitlines()[-1]
        diagnostics.insert(0, _top_level("script-error", f"script raised: {last_line}", "read the traceback in report['error'] and fix the script"))
    elif not figures:
        diagnostics.insert(0, _top_level("no-figures", "the script created no Matplotlib figure", "create a figure (plt.subplots()) and do not plt.close() it before the script ends, or call plt.show()"))

    seen = {(d["code"], d["message"]) for d in diagnostics}
    entries = []
    for index, fig in enumerate(figures):
        png = out_dir / f"{path.stem}-fig{index}.png"
        entry: dict[str, Any] = {"index": index, "png": str(png), "diagnostics": [], "snapshot": None}
        try:
            entry["diagnostics"] = [d for d in lint(fig, min_fontsize=min_fontsize) if (d["code"], d["message"]) not in seen]
            entry["snapshot"] = snapshot(fig)
            with matplotlib.rc_context({"savefig.bbox": "standard"}):
                fig.savefig(png, dpi=fig.dpi, bbox_inches=None)  # uncropped: PNG pixels match bbox_display
        except Exception:  # noqa: BLE001 - a broken figure must not hide the others
            entry["diagnostics"] = [_top_level("script-error", f"inspecting figure {index} failed", traceback.format_exc().strip().splitlines()[-1])]
        entries.append(entry)
        plt.close(fig)

    everything = diagnostics + [d for entry in entries for d in entry["diagnostics"]]
    report = {
        "schema_version": SCHEMA_VERSION,
        "script": str(path),
        "argv": list(script_args or []),
        "status": "script-error" if error else ("no-figures" if not figures else "ok"),
        "error": error,
        "summary": {severity: sum(d["severity"] == severity for d in everything) for severity in SEVERITIES},
        "diagnostics": diagnostics,
        "figures": entries,
    }
    report_path = out_dir / f"{path.stem}.json"
    report["report"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2))
    return report


@contextmanager
def _capture_figures(figures: list[Any]) -> Iterator[list[warnings.WarningMessage]]:
    """Record figures handed to plt.show/plt.close/savefig, plus warnings.

    Also pins the backend: ``matplotlib.use`` calls inside the script are
    ignored so it cannot switch to a GUI backend.
    """
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure

    saved = plt.show, plt.close, Figure.savefig, matplotlib.use
    close, savefig = plt.close, Figure.savefig

    def patched_close(*args: Any, **kwargs: Any) -> None:
        _remember(figures, *_open_figures())
        close(*args, **kwargs)

    def patched_savefig(fig: Figure, *args: Any, **kwargs: Any) -> Any:
        _remember(figures, fig)
        return savefig(fig, *args, **kwargs)

    plt.show = lambda *args, **kwargs: _remember(figures, *_open_figures())
    plt.close, Figure.savefig = patched_close, patched_savefig
    matplotlib.use = lambda *args, **kwargs: None
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("default")
            yield caught
    finally:
        plt.show, plt.close, Figure.savefig, matplotlib.use = saved


def _open_figures() -> Iterator[Any]:
    from matplotlib._pylab_helpers import Gcf

    for manager in Gcf.get_all_fig_managers():
        yield manager.canvas.figure


def _remember(figures: list[Any], *new: Any) -> None:
    for fig in new:
        if not any(fig is known for known in figures):
            figures.append(fig)


def _top_level(code: str, message: str, fix: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": CODES[code][0],
        "message": message,
        "fix": fix,
        "location": {"axes": None, "target": None, "bbox_display": None},
    }


def _print_summary(report: dict[str, Any]) -> None:
    def line(where: str, diag: dict[str, Any]) -> None:
        target = diag["location"]["target"]
        place = f"{where} {target}" if target else where
        print(f"[{diag['severity']}] {place} {diag['code']}: {diag['message']}")
        print(f"    fix: {diag['fix']}")

    for diag in report["diagnostics"]:
        line("script", diag)
    for entry in report["figures"]:
        for diag in entry["diagnostics"]:
            line(f"fig{entry['index']}", diag)
    if report["error"]:
        print(report["error"].rstrip())
    counts = ", ".join(f"{report['summary'][s]} {s}" for s in SEVERITIES)
    pngs = " ".join(entry["png"] for entry in report["figures"]) or "none"
    print(f"{len(report['figures'])} figure(s): {counts}")
    print(f"report: {report['report']}")
    print(f"png: {pngs}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
