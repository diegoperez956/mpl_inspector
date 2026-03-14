import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import mpl_inspector as mpl_inspector


def test_dump_tree_unfiltered(capsys):
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="line")
    ax.scatter([0.5], [0.5], label="dot")
    ax.text(0.3, 0.3, "hello")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    tree = inspector.dump_tree()

    assert "Line2D" in tree
    assert "PathCollection" in tree
    assert "Text" in tree

    plt.close(fig)


def test_dump_tree_filter_by_type(capsys):
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="line")
    ax.scatter([0.5], [0.5], label="dot")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    tree = inspector.dump_tree(filter_type=Line2D)

    assert "Line2D" in tree
    assert "PathCollection" not in tree

    plt.close(fig)


def test_dump_tree_filter_by_label(capsys):
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="alpha")
    ax.plot([0, 1], [1, 0], label="beta")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    tree = inspector.dump_tree(filter_label="alpha")

    assert "alpha" in tree
    assert "beta" not in tree

    plt.close(fig)


def test_dump_tree_exclude_hidden(capsys):
    fig, ax = plt.subplots()
    line1, = ax.plot([0, 1], [0, 1], label="visible")
    line2, = ax.plot([0, 1], [1, 0], label="hidden")
    line2.set_visible(False)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    tree = inspector.dump_tree(include_hidden=False)

    assert "visible" in tree
    assert "hidden" not in tree

    plt.close(fig)


def test_dump_tree_shows_provenance(capsys):
    fig, ax = plt.subplots()
    ax.scatter([1], [1], label="pts")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    tree = inspector.dump_tree()

    assert "ax.scatter()" in tree

    plt.close(fig)
