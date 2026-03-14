import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

import mpl_inspector as mpl_inspector


def test_breadcrumb_for_line():
    fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1], label="diag")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    metadata = inspector.describe_artist(line)

    assert "Figure" in metadata.breadcrumb
    assert "Axes" in metadata.breadcrumb
    assert "Line2D" in metadata.breadcrumb
    assert "diag" in metadata.breadcrumb

    plt.close(fig)


def test_breadcrumb_for_axes():
    fig, ax = plt.subplots()
    ax.set_title("myplot")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    metadata = inspector.describe_artist(ax)

    assert "Figure" in metadata.breadcrumb
    assert "Axes" in metadata.breadcrumb
    # Axes should be the terminal element, not duplicated
    assert metadata.breadcrumb.count("Axes") == 1

    plt.close(fig)


def test_to_dict_contains_expected_keys():
    fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1, 2], [2, 1, 3], label="test-line")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    metadata = inspector.describe_artist(line)
    d = metadata.to_dict()

    assert d["title"] == "Line2D"
    assert d["subtitle"] == "test-line"
    assert "breadcrumb" in d
    assert "properties" in d
    assert d["properties"]["label"] == "test-line"
    assert "data" in d
    assert d["data"]["points"] == 3

    plt.close(fig)


def test_to_dict_is_json_serializable():
    import json

    fig, ax = plt.subplots()
    ax.scatter([1, 2], [3, 4], label="pts")
    ax.bar(["a"], [1])
    ax.imshow(np.random.rand(5, 5))
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)

    for artist in list(ax.lines) + list(ax.collections) + list(ax.patches) + list(ax.images):
        metadata = inspector.describe_artist(artist)
        serialized = json.dumps(metadata.to_dict())
        assert isinstance(serialized, str)

    plt.close(fig)


def test_scatter_per_point_detail():
    fig, ax = plt.subplots()
    sc = ax.scatter([10, 20, 30], [40, 50, 60])
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    hit = {"ind": np.array([1])}
    metadata = inspector.describe_artist(sc, hit=hit)

    assert metadata.data["hit_indices"] == [1]
    assert "  [1]" in metadata.data
    assert "20" in metadata.data["  [1]"]
    assert "50" in metadata.data["  [1]"]

    plt.close(fig)


def test_patch_adapter_for_rectangle():
    fig, ax = plt.subplots()
    bars = ax.bar(["x", "y"], [3, 5])
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    rect = bars.patches[0]
    metadata = inspector.describe_artist(rect)

    assert metadata.title == "Rectangle"
    assert "width" in metadata.data
    assert "height" in metadata.data

    plt.close(fig)


def test_image_adapter():
    fig, ax = plt.subplots()
    img = ax.imshow(np.random.rand(10, 12), cmap="viridis")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    metadata = inspector.describe_artist(img)

    assert metadata.title == "AxesImage"
    assert metadata.properties["cmap"] == "viridis"
    assert "10x12" in metadata.data["shape"]

    plt.close(fig)


def test_legend_adapter():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="a")
    ax.plot([0, 1], [1, 0], label="b")
    legend = ax.legend()
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    metadata = inspector.describe_artist(legend)

    assert metadata.title == "Legend"
    assert metadata.properties["entries"] == 2
    assert "a" in metadata.data["labels"]
    assert "b" in metadata.data["labels"]

    plt.close(fig)


def test_text_adapter():
    fig, ax = plt.subplots()
    text = ax.text(0.5, 0.5, "hello world", fontsize=14)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    metadata = inspector.describe_artist(text)

    assert metadata.title == "Text"
    assert metadata.properties["text"] == "hello world"
    assert metadata.properties["fontsize"] == 14.0

    plt.close(fig)


def test_figure_adapter():
    fig, ax = plt.subplots(2, 2, figsize=(10, 8))
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    metadata = inspector.describe_artist(fig)

    assert metadata.title == "Figure"
    assert metadata.properties["axes"] == 4
    assert "10" in metadata.properties["size_inches"]

    plt.close(fig)


def test_axes_adapter():
    fig, ax = plt.subplots()
    ax.set_title("My Plot")
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_xlim(0, 10)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    metadata = inspector.describe_artist(ax)

    assert metadata.title == "Axes"
    assert metadata.properties["title"] == "My Plot"
    assert metadata.properties["xlabel"] == "X"
    assert metadata.properties["ylabel"] == "Y"
    assert metadata.properties["xscale"] == "linear"

    plt.close(fig)
