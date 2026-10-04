import warnings

import matplotlib.pyplot as plt
import numpy as np
import pytest

from mpl_inspector import CODES, lint
from mpl_inspector.lint import cvd_delta_e, warning_diagnostics

CLI_ONLY = {"script-error", "no-figures", "runtime-warning"}


def _labeled(ax, title="t"):
    ax.set(title=title, xlabel="x", ylabel="y")
    return ax


def clean_figure():
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3], [1, 4, 9], label="squares")
    ax.legend(loc="upper left")
    _labeled(ax)
    return fig


# One synthetic figure per diagnostic code. Each must trigger its code.


def tick_label_overlap():
    fig, ax = plt.subplots(figsize=(4, 3))
    ax.bar([f"category number {i}" for i in range(8)], range(1, 9))
    return fig


def text_overlap():
    fig, ax = plt.subplots()
    ax.plot([0, 1])
    ax.text(0.5, 0.5, "first label", transform=ax.transAxes)
    ax.text(0.52, 0.5, "second label", transform=ax.transAxes)
    return fig


def text_cut_off():
    fig, ax = plt.subplots()
    ax.plot([1, 2])
    ax.set_ylabel("a very long label\n" * 2, fontsize=40)
    return fig


def artist_outside_limits():
    fig, ax = plt.subplots()
    ax.plot([1, 2], [1, 2])
    ax.set_xlim(5, 6)
    return fig


def axes_overlap():
    fig = plt.figure()
    fig.add_axes([0.1, 0.1, 0.5, 0.5]).plot([1, 2])
    fig.add_axes([0.4, 0.4, 0.5, 0.5]).plot([1, 2])
    return fig


def axes_collapsed():
    fig = plt.figure()
    fig.add_axes([0.1, 0.1, 0.001, 0.5]).plot([1, 2])
    return fig


def data_clipped():
    fig, ax = plt.subplots()
    ax.plot([1, -1, 2], [1, 2, 3])
    ax.set_xscale("log")
    return fig


def legend_covers_data():
    fig, ax = plt.subplots()
    ax.plot(range(10), label="up")
    ax.plot(range(10)[::-1], label="down")
    ax.legend(loc="center")
    return fig


def missing_axis_label():
    fig, ax = plt.subplots()
    ax.plot([1, 2])
    ax.set_title("t")
    return fig


def missing_title():
    fig, ax = plt.subplots()
    ax.plot([1, 2])
    ax.set(xlabel="x", ylabel="y")
    return fig


def small_font():
    fig, ax = plt.subplots()
    ax.plot([1, 2])
    ax.tick_params(labelsize=5)
    return fig


def low_contrast():
    fig, ax = plt.subplots()
    ax.plot([1, 2], color="#ffff66")
    ax.text(1, 1.5, "faint", color="#dddddd")
    return fig


def colorblind_unsafe():
    fig, ax = plt.subplots()
    ax.plot([1, 2], color="#2ca02c", label="green")
    ax.plot([2, 1], color="#d62728", label="red")
    return fig


def rainbow_colormap():
    fig, ax = plt.subplots()
    ax.imshow(np.arange(16).reshape(4, 4), cmap="jet")
    return fig


def empty_axes():
    fig, axs = plt.subplots(1, 2)
    axs[0].plot([1, 2])
    return fig


def too_many_categories():
    fig, ax = plt.subplots()
    for i in range(12):
        ax.plot([0, i], label=str(i))
    ax.legend()
    return fig


def inconsistent_scales():
    fig, (a, b) = plt.subplots(1, 2, layout="constrained")
    a.plot([1, 2], [1, 10])
    b.plot([1, 2], [1, 100])
    b.set_yscale("log")
    a.set_ylabel("T")
    b.set_ylabel("T")
    return fig


def unshared_limits():
    fig, (a, b) = plt.subplots(1, 2, layout="constrained")
    a.plot([1, 2], [1, 10])
    b.plot([1, 2], [1, 100])
    a.set_ylabel("T")
    b.set_ylabel("T")
    return fig


def layout_warning():
    fig, axs = plt.subplots(4, 4, figsize=(1.5, 1.5), layout="constrained")
    for ax in axs.flat:
        ax.plot([1, 2])
        _labeled(ax, "a long title here")
    return fig


FACTORIES = {
    "tick-label-overlap": tick_label_overlap,
    "text-overlap": text_overlap,
    "text-cut-off": text_cut_off,
    "artist-outside-limits": artist_outside_limits,
    "axes-overlap": axes_overlap,
    "axes-collapsed": axes_collapsed,
    "data-clipped": data_clipped,
    "legend-covers-data": legend_covers_data,
    "missing-axis-label": missing_axis_label,
    "missing-title": missing_title,
    "small-font": small_font,
    "low-contrast": low_contrast,
    "colorblind-unsafe": colorblind_unsafe,
    "rainbow-colormap": rainbow_colormap,
    "empty-axes": empty_axes,
    "too-many-categories": too_many_categories,
    "inconsistent-scales": inconsistent_scales,
    "unshared-limits": unshared_limits,
    "layout-warning": layout_warning,
}


def run(factory):
    fig = factory()
    try:
        return lint(fig)
    finally:
        plt.close(fig)


def test_every_code_has_a_factory():
    assert set(FACTORIES) | CLI_ONLY == set(CODES)


@pytest.mark.parametrize("code", sorted(FACTORIES))
def test_each_code_triggers(code):
    found = run(FACTORIES[code])
    matching = [d for d in found if d["code"] == code]
    assert matching, f"{code} not reported; got {[d['code'] for d in found]}"
    diag = matching[0]
    assert diag["severity"] == CODES[code][0]
    assert diag["message"] and diag["fix"]
    assert set(diag["location"]) == {"axes", "target", "bbox_display"}


def test_clean_figure_has_no_diagnostics():
    assert run(clean_figure) == []


def test_diagnostics_sorted_by_severity():
    order = ["error", "warning", "info"]
    severities = [d["severity"] for d in run(tick_label_overlap)]
    assert severities == sorted(severities, key=order.index)


def test_locations_point_at_snapshot_ids():
    found = run(artist_outside_limits)
    diag = next(d for d in found if d["code"] == "artist-outside-limits")
    assert diag["location"] == {"axes": 0, "target": "ax0.0", "bbox_display": diag["location"]["bbox_display"]}
    assert len(diag["location"]["bbox_display"]) == 4


def test_tick_overlap_is_one_diagnostic_per_axis():
    found = [d for d in run(tick_label_overlap) if d["code"] == "tick-label-overlap"]
    assert len(found) == 1
    assert found[0]["location"]["target"] == "ax0.xticklabels"
    assert "labelrotation" in found[0]["fix"]


def test_rotating_tick_labels_fixes_overlap():
    fig = tick_label_overlap()
    fig.axes[0].tick_params(axis="x", labelrotation=90)
    fig.set_layout_engine("constrained")
    codes = {d["code"] for d in lint(fig)}
    plt.close(fig)
    assert "tick-label-overlap" not in codes
    assert "text-cut-off" not in codes


def test_cross_subplot_overlaps_are_aggregated():
    fig, axs = plt.subplots(3, 1, figsize=(4, 3))
    for ax in axs:
        ax.plot([1, 2])
        _labeled(ax)
    found = [d for d in lint(fig) if d["code"] == "text-overlap"]
    plt.close(fig)
    assert len(found) == 1
    assert "constrained" in found[0]["fix"]


def test_constrained_layout_resolves_crowding():
    fig, axs = plt.subplots(3, 1, figsize=(4, 5), layout="constrained")
    for ax in axs:
        ax.plot([1, 2])
        _labeled(ax)
    codes = {d["code"] for d in lint(fig)}
    plt.close(fig)
    assert not codes & {"text-overlap", "text-cut-off"}


def test_shared_axis_label_on_sibling_is_enough():
    fig, axs = plt.subplots(2, 1, sharex=True, layout="constrained")
    for ax in axs:
        ax.plot([1, 2])
        ax.set(title="t", ylabel="y")
    axs[1].set_xlabel("time")
    codes = {d["code"] for d in lint(fig)}
    plt.close(fig)
    assert "missing-axis-label" not in codes


def test_distinct_linestyles_are_colorblind_safe():
    fig = colorblind_unsafe()
    fig.axes[0].lines[1].set_linestyle("--")
    codes = {d["code"] for d in lint(fig)}
    plt.close(fig)
    assert "colorblind-unsafe" not in codes


def test_colorblind_safe_cycle_passes():
    colors = plt.style.library["tableau-colorblind10"]["axes.prop_cycle"].by_key()["color"]
    for i, a in enumerate(colors):
        for b in colors[i + 1 :]:
            delta = cvd_delta_e(a, b)
            assert min(delta[k] for k in ("protanopia", "deuteranopia", "tritanopia")) >= 12


def test_inset_and_twin_axes_do_not_overlap():
    fig, ax = plt.subplots(layout="constrained")
    ax.plot([1, 2])
    _labeled(ax)
    twin = ax.twinx()
    twin.plot([2, 1], color="tab:red", linestyle="--")
    twin.set_ylabel("y2")
    inset = ax.inset_axes([0.6, 0.1, 0.3, 0.3])
    inset.plot([1, 2])
    codes = {d["code"] for d in lint(fig)}
    plt.close(fig)
    assert "axes-overlap" not in codes


def test_empty_figure():
    fig = plt.figure()
    found = lint(fig)
    plt.close(fig)
    assert [d["code"] for d in found] == ["empty-axes"]


def test_min_fontsize_is_configurable():
    fig = clean_figure()
    codes = {d["code"] for d in lint(fig, min_fontsize=20)}
    plt.close(fig)
    assert "small-font" in codes


def test_warning_diagnostics():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warnings.warn("Tight layout not applied.", UserWarning)
        warnings.warn("something odd", RuntimeWarning)
        warnings.warn("something odd", RuntimeWarning)
        warnings.warn("FigureCanvasAgg is non-interactive, and thus cannot be shown", UserWarning)
    codes = [d["code"] for d in warning_diagnostics(caught)]
    assert codes == ["layout-warning", "runtime-warning"]


def test_rotated_tick_labels_use_rotated_boxes():
    fig, ax = plt.subplots(figsize=(4, 3), layout="constrained")
    ax.bar([f"category number {i}" for i in range(8)], range(1, 9))
    _labeled(ax)
    ax.tick_params(axis="x", labelrotation=45)
    codes = {d["code"] for d in lint(fig)}
    assert ax.get_xticklabels()[0].get_rotation() == 45  # lint must not mutate the figure
    plt.close(fig)
    assert "tick-label-overlap" not in codes


def test_dense_rotated_tick_labels_still_overlap():
    fig, ax = plt.subplots(figsize=(3, 3))
    ax.bar([f"cat {i}" for i in range(30)], range(30))
    ax.tick_params(axis="x", labelrotation=45)
    codes = {d["code"] for d in lint(fig)}
    plt.close(fig)
    assert "tick-label-overlap" in codes


def test_agent_doc_lists_every_code():
    from pathlib import Path

    doc = (Path(__file__).parent.parent / "AGENT.md").read_text()
    assert [code for code in CODES if f"`{code}`" not in doc] == []
