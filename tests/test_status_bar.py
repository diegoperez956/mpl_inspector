import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backend_bases import MouseEvent

import mpl_inspector as mpl_inspector


def _motion_event(figure, axis, xdata, ydata):
    x_display, y_display = axis.transData.transform((xdata, ydata))
    return MouseEvent("motion_notify_event", figure.canvas, x_display, y_display)


def test_status_bar_updates_on_motion():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="diag")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    event = _motion_event(fig, ax, 0.5, 0.5)
    inspector._on_motion(event)

    status_text = inspector._panel._status_artist.get_text()
    assert "Axes" in status_text
    # Should contain cursor coordinates
    assert "x=" in status_text
    assert "y=" in status_text

    plt.close(fig)


def test_status_bar_shows_hovered_artist_type():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="myline", linewidth=5)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    event = _motion_event(fig, ax, 0.5, 0.5)
    inspector._on_motion(event)

    status_text = inspector._panel._status_artist.get_text()
    assert "Line2D" in status_text
    assert "myline" in status_text

    plt.close(fig)


def test_status_bar_hidden_when_disabled():
    fig, ax = plt.subplots()
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    inspector.disable()

    assert not inspector._panel._status_artist.get_visible()

    plt.close(fig)
