from __future__ import annotations

import warnings
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.figure import Figure


def show_in_notebook(
    figure: Figure,
    *,
    minimal_ui: bool = True,
) -> bool:
    """Display *figure* in a notebook.

    When the ipympl widget backend is active, the figure canvas is displayed as
    a live widget. Otherwise the Figure is displayed statically so the user at
    least sees the plot instead of a blank cell.
    """

    if not _running_in_ipython():
        return False

    if _is_nbagg_canvas(figure) and not _is_widget_canvas(figure):
        manager = getattr(figure.canvas, "manager", None)
        if manager is not None and hasattr(manager, "show"):
            manager.show()
        else:
            plt.show()
        return True

    try:
        from IPython.display import display
    except ImportError:
        return False

    if _is_widget_canvas(figure):
        if minimal_ui:
            configure_widget_canvas(figure, minimal_ui=minimal_ui)
        display(figure.canvas)
        return True

    # Static notebook fallback: still display the figure even if interaction
    # features are unavailable under the current backend.
    display(figure)
    return True


def configure_widget_canvas(
    figure: Figure,
    *,
    minimal_ui: bool = True,
    responsive: bool = True,
) -> None:
    """Apply a compact ipympl widget presentation when supported."""

    canvas = figure.canvas
    if not _is_widget_canvas(figure):
        return

    if minimal_ui:
        canvas.toolbar_visible = False
    elif getattr(canvas, "toolbar_visible", None) is not None:
        canvas.toolbar_visible = True

    if hasattr(canvas, "header_visible"):
        canvas.header_visible = False
    if hasattr(canvas, "footer_visible"):
        canvas.footer_visible = False
    if hasattr(canvas, "capture_scroll"):
        canvas.capture_scroll = True
    if hasattr(canvas, "toolbar_position") and getattr(canvas, "toolbar_visible", None):
        canvas.toolbar_position = "right"
    if responsive:
        autosize_widget_canvas(figure)


def autosize_widget_canvas(
    figure: Figure,
    *,
    width: str = "100%",
    min_height_px: int = 360,
    extra_height_px: int = 24,
    target_width_px: int = 980,
    max_height_px: int = 720,
) -> None:
    """Give ipympl canvases a more notebook-friendly responsive layout."""

    canvas = figure.canvas
    layout = getattr(canvas, "layout", None)
    if not _is_widget_canvas(figure) or layout is None:
        return

    fit_figure_to_cell(
        figure,
        target_width_px=target_width_px,
        max_height_px=max_height_px,
    )

    pixel_height = max(int(round(figure.get_figheight() * figure.dpi)) + extra_height_px, min_height_px)

    if hasattr(layout, "width"):
        layout.width = width
    if hasattr(layout, "max_width"):
        layout.max_width = width
    if hasattr(layout, "height"):
        layout.height = f"{pixel_height}px"
    if hasattr(layout, "min_height"):
        layout.min_height = f"{pixel_height}px"
    if hasattr(layout, "max_height"):
        layout.max_height = f"{pixel_height}px"
    if hasattr(layout, "flex"):
        layout.flex = "1 1 auto"
    if hasattr(layout, "align_self"):
        layout.align_self = "stretch"

    if hasattr(canvas, "resizable"):
        canvas.resizable = True


def fit_figure_to_cell(
    figure: Figure,
    *,
    target_width_px: int = 980,
    max_height_px: int = 720,
) -> None:
    """Shrink overly large figures to a notebook-friendly starting size.

    This does not try to read browser cell width; it simply prevents very wide
    or very tall figures from opening at awkward default pixel sizes.
    """

    dpi = float(figure.dpi)
    width_px = float(figure.get_figwidth() * dpi)
    height_px = float(figure.get_figheight() * dpi)

    scale = 1.0
    if width_px > target_width_px:
        scale = min(scale, target_width_px / width_px)
    if height_px > max_height_px:
        scale = min(scale, max_height_px / height_px)

    if scale < 0.999:
        figure.set_size_inches(
            figure.get_figwidth() * scale,
            figure.get_figheight() * scale,
            forward=True,
        )


def warn_if_notebook_backend_is_static(figure: Figure) -> None:
    if not _running_in_ipython():
        return
    if _is_widget_canvas(figure) or _is_nbagg_canvas(figure):
        return

    warnings.warn(
        "Interactive notebook inspection requires an interactive notebook backend. "
        "Prefer `%matplotlib widget` / `%matplotlib ipympl` with `ipympl`, or use "
        "`%matplotlib notebook` in classic notebook environments.",
        stacklevel=2,
    )


def _running_in_ipython() -> bool:
    try:
        from IPython import get_ipython
    except ImportError:
        return False
    return get_ipython() is not None


def _is_widget_canvas(figure: Figure) -> bool:
    canvas = figure.canvas
    return hasattr(canvas, "header_visible") and hasattr(canvas, "toolbar_visible")


def _is_nbagg_canvas(figure: Figure) -> bool:
    if _is_widget_canvas(figure):
        return False

    canvas = figure.canvas
    backend = matplotlib.get_backend().lower()
    canvas_name = type(canvas).__name__.lower()
    canvas_module = type(canvas).__module__.lower()

    return (
        "nbagg" in backend
        or "nbagg" in canvas_name
        or "nbagg" in canvas_module
        or backend.endswith("notebook")
    )
