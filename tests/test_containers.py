import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from mpl_inspector.containers import find_container


def test_bar_rectangle_maps_to_bar_container():
    fig, ax = plt.subplots()
    container = ax.bar(["a", "b", "c"], [1, 2, 3])
    fig.canvas.draw()

    # Each Rectangle in the bars should map back to the BarContainer
    for rect in container.patches:
        found = find_container(rect)
        assert found is container

    plt.close(fig)


def test_errorbar_maps_to_errorbar_container():
    fig, ax = plt.subplots()
    container = ax.errorbar([1, 2, 3], [1, 2, 3], yerr=0.5)
    fig.canvas.draw()

    data_line = container[0]
    found = find_container(data_line)
    assert found is container

    plt.close(fig)


def test_uncontained_line_returns_none():
    fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1])
    fig.canvas.draw()

    assert find_container(line) is None
    plt.close(fig)


def test_stem_maps_to_stem_container():
    fig, ax = plt.subplots()
    container = ax.stem([1, 2, 3], [1, 2, 3])
    fig.canvas.draw()

    assert find_container(container.markerline) is container
    assert find_container(container.baseline) is container

    plt.close(fig)
