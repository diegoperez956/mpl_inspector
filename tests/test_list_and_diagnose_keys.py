import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backend_bases import KeyEvent, MouseEvent

import mpl_inspector as mpl_inspector


def _key_event(figure, key, axes=None):
    event = KeyEvent("key_press_event", figure.canvas, key)
    if axes is not None:
        event.inaxes = axes
    return event


def _click(figure, axis, xdata, ydata):
    x_display, y_display = axis.transData.transform((xdata, ydata))
    return MouseEvent("button_press_event", figure.canvas, x_display, y_display, button=1)


def test_a_key_lists_artists(capsys):
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="line1")
    ax.scatter([0.5], [0.5], label="dot")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)

    event = _key_event(fig, "a", axes=ax)
    inspector._on_key_press(event)

    captured = capsys.readouterr()
    assert "line1" in captured.out
    assert "dot" in captured.out
    assert "artists" in captured.out.lower()

    plt.close(fig)


def test_a_key_shows_provenance(capsys):
    fig, ax = plt.subplots()
    ax.scatter([1], [2], label="sc")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)

    event = _key_event(fig, "a", axes=ax)
    inspector._on_key_press(event)

    captured = capsys.readouterr()
    assert "ax.scatter()" in captured.out

    plt.close(fig)


def test_question_key_no_selection(capsys):
    fig, ax = plt.subplots()
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)

    event = _key_event(fig, "?")
    inspector._on_key_press(event)

    captured = capsys.readouterr()
    assert "No artist selected" in captured.out

    plt.close(fig)


def test_question_key_hidden_artist(capsys):
    fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1], label="hidden_line", linewidth=5)
    line.set_visible(False)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    # Directly select the hidden line
    inspector._select_artist(line, {})

    event = _key_event(fig, "?")
    inspector._on_key_press(event)

    captured = capsys.readouterr()
    assert "visible=False" in captured.out

    plt.close(fig)


def test_question_key_healthy_artist(capsys):
    fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1], label="good", linewidth=5)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    event = _click(fig, ax, 0.5, 0.5)
    inspector._on_button_press(event)

    event = _key_event(fig, "?")
    inspector._on_key_press(event)

    captured = capsys.readouterr()
    assert "no visibility issues" in captured.out

    plt.close(fig)


def test_selection_shows_provenance():
    fig, ax = plt.subplots()
    sc = ax.scatter([0.5], [0.5], s=200, label="pts")
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    inspector._select_artist(sc, {})

    panel_text = inspector._panel.text_artist.get_text()
    assert "ax.scatter()" in panel_text

    plt.close(fig)
