import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backend_bases import KeyEvent

import mpl_inspector as mpl_inspector


def _key_event(figure, key, axes=None):
    event = KeyEvent("key_press_event", figure.canvas, key)
    if axes is not None:
        event.inaxes = axes
    return event


def test_down_arrow_traverses_artists():
    fig, ax = plt.subplots()
    line1, = ax.plot([0, 1], [0, 1], label="a")
    line2, = ax.plot([0, 1], [1, 0], label="b")
    ax.scatter([0.5], [0.5], label="c")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)

    # First down arrow should select first artist
    event = _key_event(fig, "down", axes=ax)
    inspector._on_key_press(event)
    first = inspector.selected_artist
    assert first is not None

    # Second down arrow should select a different artist
    inspector._on_key_press(event)
    second = inspector.selected_artist
    assert second is not first

    plt.close(fig)


def test_up_arrow_goes_backward():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="a")
    ax.plot([0, 1], [1, 0], label="b")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)

    # Go down twice, then up once — should be back to first
    down = _key_event(fig, "down", axes=ax)
    inspector._on_key_press(down)
    first = inspector.selected_artist

    inspector._on_key_press(down)

    up = _key_event(fig, "up", axes=ax)
    inspector._on_key_press(up)
    assert inspector.selected_artist is first

    plt.close(fig)


def test_traversal_wraps_around():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="only")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)

    down = _key_event(fig, "down", axes=ax)
    # Walk through more times than there are artists — should wrap
    for _ in range(20):
        inspector._on_key_press(down)

    assert inspector.selected_artist is not None
    plt.close(fig)


def test_escape_clears_traversal():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)

    down = _key_event(fig, "down", axes=ax)
    inspector._on_key_press(down)
    assert inspector.selected_artist is not None

    esc = _key_event(fig, "escape", axes=ax)
    inspector._on_key_press(esc)
    assert inspector.selected_artist is None
    assert inspector._traversal_list == []

    plt.close(fig)
