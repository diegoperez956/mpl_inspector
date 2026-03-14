import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backend_bases import MouseEvent

import mpl_inspector as mpl_inspector


def _mouse_event(figure, axis, xdata, ydata, *, name):
    x_display, y_display = axis.transData.transform((xdata, ydata))
    return MouseEvent(name, figure.canvas, x_display, y_display, button=1)


def test_click_selects_line_artist():
    figure, axis = plt.subplots()
    (line,) = axis.plot([0, 1], [0, 1], label="diag", linewidth=3.0)
    figure.canvas.draw()

    inspector = mpl_inspector.inspect(figure, print_on_select=False)
    event = _mouse_event(figure, axis, 0.5, 0.5, name="button_press_event")
    inspector._on_button_press(event)

    assert inspector.selected_artist is line
    assert "Line2D" in inspector._panel.text_artist.get_text()

    plt.close(figure)
