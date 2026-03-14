import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

import mpl_inspector as mpl_inspector


def test_annotation_adapter():
    fig, ax = plt.subplots()
    ann = ax.annotate(
        "peak",
        xy=(1.0, 1.0),
        xytext=(0.5, 0.8),
        arrowprops={"arrowstyle": "->"},
    )
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    metadata = inspector.describe_artist(ann)

    assert metadata.title == "Annotation"
    assert metadata.properties["text"] == "peak"
    assert "xy" in metadata.data
    assert metadata.properties["xycoords"] == "data"

    plt.close(fig)


def test_spine_adapter():
    fig, ax = plt.subplots()
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    spine = ax.spines["bottom"]
    metadata = inspector.describe_artist(spine)

    assert metadata.title == "Spine"
    assert metadata.properties["spine_type"] == "bottom"
    assert "linewidth" in metadata.properties

    plt.close(fig)


def test_polycollection_adapter():
    fig, ax = plt.subplots()
    x = np.linspace(0, 2, 20)
    ax.fill_between(x, 0, x**2, alpha=0.5, label="fill")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    poly = ax.collections[0]
    metadata = inspector.describe_artist(poly)

    assert "PolyCollection" in metadata.title  # FillBetweenPolyCollection subclass
    assert "paths" in metadata.data
    assert "total_vertices" in metadata.data
    assert metadata.data["total_vertices"] > 0

    plt.close(fig)


def test_quadmesh_adapter():
    fig, ax = plt.subplots()
    data = np.random.rand(5, 5)
    mesh = ax.pcolormesh(data, cmap="coolwarm")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    metadata = inspector.describe_artist(mesh)

    assert "QuadMesh" in metadata.title
    assert metadata.properties["cmap"] == "coolwarm"
    assert "value_range" in metadata.data

    plt.close(fig)


def test_axes_adapter_has_formatter_locator():
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [0, 1, 4])
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    metadata = inspector.describe_artist(ax)

    assert "xformatter" in metadata.properties
    assert "yformatter" in metadata.properties
    assert "xlocator" in metadata.properties
    assert "ylocator" in metadata.properties
    assert "aspect" in metadata.properties
    assert "autoscale_on" in metadata.properties
    assert "containers" in metadata.data

    plt.close(fig)
