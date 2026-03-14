import json
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backend_bases import MouseEvent

import mpl_inspector as mpl_inspector


def _click(figure, axis, xdata, ydata):
    x_display, y_display = axis.transData.transform((xdata, ydata))
    return MouseEvent("button_press_event", figure.canvas, x_display, y_display, button=1)


def test_dump_prints_json(capsys):
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="test-line", linewidth=3)
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)

    # Select the line
    event = _click(fig, ax, 0.5, 0.5)
    inspector._on_button_press(event)

    # Dump
    inspector._dump_selected()
    captured = capsys.readouterr()

    # Should be valid JSON
    parsed = json.loads(captured.out.split("\n[inspector]")[0])
    assert parsed["title"] == "Line2D"
    assert parsed["properties"]["label"] == "test-line"

    plt.close(fig)


def test_dump_with_no_selection(capsys):
    fig, ax = plt.subplots()
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)
    inspector._dump_selected()

    captured = capsys.readouterr()
    assert "No artist selected" in captured.out

    plt.close(fig)


def test_dump_includes_container_info(capsys):
    fig, ax = plt.subplots()
    bars = ax.bar(["a", "b"], [1, 2])
    fig.canvas.draw()

    inspector = mpl_inspector.inspect(fig, print_on_select=False)

    # Directly select the first bar rectangle
    inspector._select_artist(bars.patches[0], {})
    inspector._dump_selected()

    captured = capsys.readouterr()
    parsed = json.loads(captured.out.split("\n[inspector]")[0])

    assert "container" in parsed.get("relationships", {})
    assert "BarContainer" in parsed["relationships"]["container"]

    plt.close(fig)
