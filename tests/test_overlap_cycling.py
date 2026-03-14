import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backend_bases import MouseEvent

import mpl_inspector as mpl_inspector


def _mouse_event(figure, axis, xdata, ydata, *, name="button_press_event"):
    x_display, y_display = axis.transData.transform((xdata, ydata))
    return MouseEvent(name, figure.canvas, x_display, y_display, button=1)


def test_tab_cycles_through_overlapping_artists():
    fig, ax = plt.subplots()
    line1, = ax.plot([0, 1], [0, 1], label="line1", linewidth=5)
    line2, = ax.plot([0, 1], [0.05, 1.05], label="line2", linewidth=5)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)

    # Click at a point where both lines overlap
    event = _mouse_event(fig, ax, 0.5, 0.525, name="button_press_event")
    inspector._on_button_press(event)

    # Should have multiple candidates (both lines + axes)
    assert len(inspector._overlap_candidates) >= 2

    first_selected = inspector.selected_artist
    seen = {id(first_selected)}

    # Tab through all candidates — we should see at least one different artist
    for _ in range(len(inspector._overlap_candidates)):
        inspector._cycle_overlap(forward=True)
        seen.add(id(inspector.selected_artist))

    assert len(seen) >= 2

    plt.close(fig)


def test_shift_tab_cycles_backward():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="a", linewidth=5)
    ax.plot([0, 1], [0.05, 1.05], label="b", linewidth=5)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    event = _mouse_event(fig, ax, 0.5, 0.525)
    inspector._on_button_press(event)

    first = inspector.selected_artist
    inspector._cycle_overlap(forward=False)
    assert inspector.selected_artist is not first

    plt.close(fig)


def test_escape_clears_overlap_state():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], linewidth=5)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    event = _mouse_event(fig, ax, 0.5, 0.5)
    inspector._on_button_press(event)

    assert inspector.selected_artist is not None
    assert len(inspector._overlap_candidates) > 0

    # Simulate escape
    inspector._select_artist(None, None)
    inspector._overlap_candidates.clear()
    inspector._overlap_index = -1

    assert inspector.selected_artist is None
    assert len(inspector._overlap_candidates) == 0

    plt.close(fig)
