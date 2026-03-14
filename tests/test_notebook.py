import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from types import SimpleNamespace

import mpl_inspector as mpl_inspector
from mpl_inspector import inspector as inspector_mod
from mpl_inspector import notebook as notebook_mod


def test_show_falls_back_to_pyplot_show(monkeypatch):
    fig, _ = plt.subplots()
    fig.canvas.draw()

    called = {"show": 0}

    def fake_show():
        called["show"] += 1

    monkeypatch.setattr(notebook_mod, "_running_in_ipython", lambda: False)
    monkeypatch.setattr(plt, "show", fake_show)

    inspector = mpl_inspector.show(fig, print_on_select=False)

    assert inspector.figure is fig
    assert called["show"] == 1

    plt.close(fig)


def test_configure_widget_canvas_hides_widget_chrome():
    fig, _ = plt.subplots(figsize=(20, 10))
    canvas = fig.canvas
    canvas.toolbar_visible = True
    canvas.header_visible = True
    canvas.footer_visible = True
    canvas.capture_scroll = False
    canvas.layout = SimpleNamespace(
        width=None,
        max_width=None,
        height=None,
        min_height=None,
        max_height=None,
        flex=None,
        align_self=None,
    )
    canvas.resizable = False

    mpl_inspector.configure_widget_canvas(fig)

    assert canvas.toolbar_visible is False
    assert canvas.header_visible is False
    assert canvas.footer_visible is False
    assert canvas.capture_scroll is True
    assert canvas.layout.width == "100%"
    assert canvas.layout.max_width == "100%"
    assert canvas.layout.height.endswith("px")
    assert canvas.layout.min_height.endswith("px")
    assert canvas.layout.max_height.endswith("px")
    assert canvas.layout.flex == "1 1 auto"
    assert canvas.layout.align_self == "stretch"
    assert canvas.resizable is True
    assert fig.get_figwidth() < 20

    plt.close(fig)


def test_show_in_notebook_static_fallback(monkeypatch):
    fig, _ = plt.subplots()
    fig.canvas.draw()

    displayed = []

    class FakeDisplayModule:
        @staticmethod
        def display(value):
            displayed.append(value)

    monkeypatch.setattr(notebook_mod, "_running_in_ipython", lambda: True)
    monkeypatch.setattr(notebook_mod, "_is_widget_canvas", lambda figure: False)
    import sys
    old_module = sys.modules.get("IPython.display")
    sys.modules["IPython.display"] = FakeDisplayModule
    try:
        assert notebook_mod.show_in_notebook(fig) is True
    finally:
        if old_module is None:
            del sys.modules["IPython.display"]
        else:
            sys.modules["IPython.display"] = old_module

    assert displayed == [fig]

    plt.close(fig)


def test_show_in_notebook_nbagg_uses_manager_show(monkeypatch):
    fig, _ = plt.subplots()
    fig.canvas.draw()

    called = {"show": 0}

    class Manager:
        @staticmethod
        def show():
            called["show"] += 1

    monkeypatch.setattr(notebook_mod, "_running_in_ipython", lambda: True)
    monkeypatch.setattr(notebook_mod, "_is_widget_canvas", lambda figure: False)
    monkeypatch.setattr(notebook_mod, "_is_nbagg_canvas", lambda figure: True)
    fig.canvas.manager = Manager()

    assert notebook_mod.show_in_notebook(fig) is True
    assert called["show"] == 1

    plt.close(fig)


def test_display_uses_display_path(monkeypatch):
    fig, _ = plt.subplots()
    fig.canvas.draw()

    calls = []
    monkeypatch.setattr(inspector_mod, "_display_figure", lambda figure: calls.append(figure))

    inspector = mpl_inspector.display(fig, print_on_select=False)

    assert inspector.figure is fig
    assert calls == [fig]

    plt.close(fig)


def test_inspect_display_true_uses_display_path(monkeypatch):
    fig, _ = plt.subplots()
    fig.canvas.draw()

    calls = []
    monkeypatch.setattr(inspector_mod, "_display_figure", lambda figure: calls.append(figure))

    inspector = mpl_inspector.inspect(fig, print_on_select=False, display=True)

    assert inspector.figure is fig
    assert calls == [fig]

    plt.close(fig)


def test_fit_figure_to_cell_shrinks_large_figures():
    fig, _ = plt.subplots(figsize=(24, 12), dpi=100)
    original = fig.get_size_inches().copy()

    mpl_inspector.fit_figure_to_cell(fig, target_width_px=960, max_height_px=640)

    width, height = fig.get_size_inches()
    assert width < original[0]
    assert height < original[1]
    assert width * fig.dpi <= 960.5
    assert height * fig.dpi <= 640.5

    plt.close(fig)
