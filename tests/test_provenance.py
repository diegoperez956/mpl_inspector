import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from mpl_inspector.provenance import infer_call


def test_infer_plot():
    fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1, 2], [0, 1, 2])
    fig.canvas.draw()

    assert infer_call(line) == "ax.plot()"
    plt.close(fig)


def test_infer_scatter():
    fig, ax = plt.subplots()
    sc = ax.scatter([1, 2], [3, 4])
    fig.canvas.draw()

    assert infer_call(sc) == "ax.scatter()"
    plt.close(fig)


def test_infer_bar():
    fig, ax = plt.subplots()
    bars = ax.bar(["a", "b"], [1, 2])
    fig.canvas.draw()

    result = infer_call(bars.patches[0])
    assert "bar" in result.lower()
    plt.close(fig)


def test_infer_errorbar():
    fig, ax = plt.subplots()
    container = ax.errorbar([1, 2], [1, 2], yerr=0.5)
    fig.canvas.draw()

    data_line = container[0]
    assert infer_call(data_line) == "ax.errorbar()"
    plt.close(fig)


def test_infer_stem():
    fig, ax = plt.subplots()
    container = ax.stem([1, 2, 3], [1, 2, 3])
    fig.canvas.draw()

    assert "stem" in infer_call(container.markerline).lower()
    assert "stem" in infer_call(container.baseline).lower()
    plt.close(fig)


def test_infer_imshow():
    fig, ax = plt.subplots()
    img = ax.imshow(np.random.rand(5, 5))
    fig.canvas.draw()

    assert infer_call(img) == "ax.imshow()"
    plt.close(fig)


def test_infer_pcolormesh():
    fig, ax = plt.subplots()
    mesh = ax.pcolormesh(np.random.rand(5, 5))
    fig.canvas.draw()

    result = infer_call(mesh)
    assert "pcolormesh" in result or "pcolor" in result
    plt.close(fig)


def test_infer_fill_between():
    fig, ax = plt.subplots()
    x = np.linspace(0, 1, 10)
    ax.fill_between(x, 0, x)
    fig.canvas.draw()

    poly = ax.collections[0]
    result = infer_call(poly)
    assert "fill_between" in result
    plt.close(fig)


def test_infer_text():
    fig, ax = plt.subplots()
    text = ax.text(0.5, 0.5, "hello")
    fig.canvas.draw()

    assert infer_call(text) == "ax.text()"
    plt.close(fig)


def test_infer_annotate():
    fig, ax = plt.subplots()
    ann = ax.annotate("note", xy=(0.5, 0.5))
    fig.canvas.draw()

    assert infer_call(ann) == "ax.annotate()"
    plt.close(fig)


def test_infer_legend():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="a")
    legend = ax.legend()
    fig.canvas.draw()

    assert infer_call(legend) == "ax.legend()"
    plt.close(fig)


def test_infer_spine():
    fig, ax = plt.subplots()
    fig.canvas.draw()

    spine = ax.spines["left"]
    result = infer_call(spine)
    assert "spines" in result and "left" in result
    plt.close(fig)


def test_infer_set_title():
    fig, ax = plt.subplots()
    ax.set_title("My Title")
    fig.canvas.draw()

    assert infer_call(ax.title) == "ax.set_title()"
    plt.close(fig)


def test_infer_set_xlabel():
    fig, ax = plt.subplots()
    ax.set_xlabel("X Axis")
    fig.canvas.draw()

    assert infer_call(ax.xaxis.label) == "ax.set_xlabel()"
    plt.close(fig)


def test_infer_axhspan():
    fig, ax = plt.subplots()
    rect = ax.axhspan(0.2, 0.8)
    fig.canvas.draw()

    assert infer_call(rect) == "ax.axhspan()"
    plt.close(fig)
