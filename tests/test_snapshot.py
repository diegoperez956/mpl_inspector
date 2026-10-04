import json

import matplotlib.pyplot as plt
import numpy as np
import pytest

from mpl_inspector import SCHEMA_VERSION, lint, snapshot
from mpl_inspector.snapshot import artist_ids

FIGURE_KEYS = {"schema_version", "type", "size_inches", "dpi", "size_px", "facecolor", "suptitle", "layout_engine", "texts", "legends", "axes"}
AXES_KEYS = {
    "id", "index", "visible", "axis_on", "is_colorbar", "title", "xlabel", "ylabel", "xaxis", "yaxis",
    "aspect", "facecolor", "bbox_display", "bbox_figure", "legend", "artists",
}
AXIS_KEYS = {"label", "scale", "lim", "inverted", "units", "shared_with"}
ARTIST_KEYS = {
    "id", "type", "call", "container", "label", "visible", "alpha", "zorder", "clip_on",
    "bbox_display", "bbox_data", "n_points", "data_extent", "colors",
}


@pytest.fixture
def snap():
    fig, (a, b, c) = plt.subplots(1, 3, figsize=(9, 3), layout="constrained")
    a.plot([1, 2, 3], [4, 5, 6], label="line", color="red")
    a.axhline(5)
    a.scatter([1, 2], [3, 4], c=[1, 2])
    a.legend()
    a.set(title="A", xlabel="x", ylabel="y")
    b.bar(["p", "q"], [1, 2])
    b.text(0, 1, "note")
    c.imshow(np.arange(9).reshape(3, 3))
    fig.suptitle("Suite")
    result = snapshot(fig)
    yield result
    plt.close(fig)


def test_schema_shape(snap):
    assert set(snap) == FIGURE_KEYS
    assert snap["schema_version"] == SCHEMA_VERSION
    assert snap["suptitle"] == "Suite"
    assert "Suite" not in [t["text"] for t in snap["texts"]]
    assert snap["layout_engine"] == "constrained"
    for ax in snap["axes"]:
        assert set(ax) == AXES_KEYS
        assert set(ax["xaxis"]) == AXIS_KEYS
        for artist in ax["artists"]:
            assert ARTIST_KEYS <= set(artist)


def test_valid_strict_json(snap):
    json.loads(json.dumps(snap, allow_nan=False))


def test_line_record(snap):
    line = snap["axes"][0]["artists"][0]
    assert line["id"] == "ax0.0"
    assert line["type"] == "Line2D"
    assert line["call"] == "ax.plot()"
    assert line["label"] == "line"
    assert line["colors"]["color"] == "#ff0000"
    assert line["n_points"] == 3
    assert line["data_extent"] == {"x": [1.0, 3.0], "y": [4.0, 6.0]}
    assert line["bbox_data"] == pytest.approx([1.0, 4.0, 3.0, 6.0], abs=1e-6)
    x0, y0, x1, y1 = line["bbox_display"]
    assert x1 > x0 and y1 > y0


def test_axhline_has_no_data_extent(snap):
    hline = snap["axes"][0]["artists"][1]
    assert hline["call"] == "ax.axhline()"
    assert hline["data_extent"] is None
    assert hline["bbox_data"][1] == pytest.approx(5.0)


def test_scatter_bar_text_image(snap):
    scatter = snap["axes"][0]["artists"][2]
    assert scatter["call"] == "ax.scatter()"
    assert scatter["n_points"] == 2
    assert scatter["colors"]["cmap"] == "viridis"
    assert scatter["bbox_display"] is not None

    bars = [a for a in snap["axes"][1]["artists"] if a["type"] == "Rectangle"]
    assert [b["container"] for b in bars] == ["BarContainer", "BarContainer"]
    assert bars[1]["data_extent"] == {"x": [0.6, 1.4], "y": [0.0, 2.0]}
    assert snap["axes"][1]["xaxis"]["units"] == "category"

    text = next(a for a in snap["axes"][1]["artists"] if a["type"] == "Text")
    assert text["text"] == "note"
    assert text["fontsize"] > 0

    image = snap["axes"][2]["artists"][0]
    assert image["call"] == "ax.imshow()"
    assert image["n_points"] == 9
    assert image["data_extent"] == {"x": [-0.5, 2.5], "y": [-0.5, 2.5]}


def test_axes_and_legend(snap):
    ax = snap["axes"][0]
    assert (ax["title"], ax["xlabel"], ax["ylabel"]) == ("A", "x", "y")
    assert ax["xaxis"]["scale"] == "linear"
    assert ax["legend"]["entries"] == ["line"]
    assert len(ax["legend"]["bbox_display"]) == 4


def test_ids_match_artist_ids():
    fig, ax = plt.subplots()
    line, = ax.plot([1, 2])
    patch = ax.add_patch(plt.Rectangle((0, 0), 1, 1))
    ids = artist_ids(fig)
    snap = snapshot(fig)
    plt.close(fig)
    assert {a["id"] for a in snap["axes"][0]["artists"]} == {ids[id(line)], ids[id(patch)]}


def test_shared_axes_log_scale_and_nan():
    fig, (a, b) = plt.subplots(2, 1, sharex=True)
    a.plot([1, np.nan, 3], [1, 2, np.inf])
    b.plot([1, 10, 100], [1, 2, 3])
    b.set_yscale("log")
    b.invert_yaxis()
    snap = snapshot(fig)
    plt.close(fig)
    json.dumps(snap, allow_nan=False)
    assert snap["axes"][0]["xaxis"]["shared_with"] == ["ax1"]
    assert snap["axes"][1]["yaxis"]["scale"] == "log"
    assert snap["axes"][1]["yaxis"]["inverted"] is True
    assert snap["axes"][0]["artists"][0]["data_extent"] == {"x": [1.0, 1.0], "y": [1.0, 1.0]}


def test_colorbar_and_hidden_artist():
    fig, ax = plt.subplots()
    mesh = ax.pcolormesh(np.arange(4).reshape(2, 2))
    fig.colorbar(mesh)
    ax.plot([0, 1], visible=False)
    snap = snapshot(fig)
    plt.close(fig)
    assert [a["is_colorbar"] for a in snap["axes"]] == [False, True]
    line, mesh_record = snap["axes"][0]["artists"]  # lines come before collections
    assert line["visible"] is False
    assert mesh_record["call"] == "ax.pcolormesh() / ax.pcolor()"
    assert mesh_record["colors"]["cmap"] == "viridis"


def test_fresh_figure_needs_no_manual_draw():
    fig = plt.figure()
    fig.add_subplot().plot([1, 2])
    snap = snapshot(fig)
    plt.close(fig)
    assert snap["axes"][0]["bbox_display"] is not None


def test_subfigure_axes_use_root_numbering():
    fig = plt.figure(figsize=(8, 3))
    left, right = fig.subfigures(1, 2)
    left.subplots().plot([1, 2])
    a, b = right.subplots(1, 2, sharey=True)
    a.plot([3, 4])
    b.plot([5, 6])
    snap = snapshot(fig)
    assert [ax["id"] for ax in snap["axes"]] == ["ax0", "ax1", "ax2"]
    assert [ax["index"] for ax in snap["axes"]] == [0, 1, 2]
    assert [ax["artists"][0]["id"] for ax in snap["axes"]] == ["ax0.0", "ax1.0", "ax2.0"]
    assert snap["axes"][1]["yaxis"]["shared_with"] == ["ax2"]
    targets = {d["location"]["target"] for d in lint(fig) if d["code"] == "missing-title"}
    assert targets == {"ax0.title", "ax1.title", "ax2.title"}
    plt.close(fig)
