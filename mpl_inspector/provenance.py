"""Infer the likely plotting call that created an artist.

This is heuristic-based — it maps artist types and their properties
back to the most probable ``Axes`` method that produced them. Not
guaranteed to be correct, but useful for the "what made this?" question.
"""

from __future__ import annotations

from typing import Any

from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.collections import (
    Collection,
    LineCollection,
    PathCollection,
    PolyCollection,
)
from matplotlib.container import BarContainer, ErrorbarContainer, StemContainer
from matplotlib.image import AxesImage
from matplotlib.legend import Legend
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, Patch, Rectangle, Wedge
from matplotlib.spines import Spine
from matplotlib.text import Annotation, Text

try:
    from matplotlib.collections import QuadMesh
except ImportError:  # pragma: no cover
    QuadMesh = None  # type: ignore[misc,assignment]

try:
    from matplotlib.contour import ContourSet
except ImportError:  # pragma: no cover
    ContourSet = None  # type: ignore[misc,assignment]


def infer_call(artist: Artist) -> str | None:
    """Return a best-guess string like ``'ax.bar()'`` for the plotting call
    that likely created *artist*, or ``None`` if unknown.

    Also checks containers first for composite artists.
    """
    axes: Axes | None = getattr(artist, "axes", None)

    # Check container membership first
    if axes is not None:
        for container in axes.containers:
            if isinstance(container, BarContainer):
                if artist in container.patches:
                    return "ax.bar() / ax.barh()"
            if isinstance(container, ErrorbarContainer):
                data_line, cap_lines, bar_lines = container
                if artist is data_line:
                    return "ax.errorbar()"
                if cap_lines and artist in cap_lines:
                    return "ax.errorbar() [cap]"
                if bar_lines and artist in bar_lines:
                    return "ax.errorbar() [bars]"
            if isinstance(container, StemContainer):
                if artist is container.markerline:
                    return "ax.stem() [markers]"
                if artist is container.stemlines:
                    return "ax.stem() [stems]"
                if artist is container.baseline:
                    return "ax.stem() [baseline]"

    # Type-based inference
    if isinstance(artist, Annotation):
        return "ax.annotate()"

    if isinstance(artist, Text):
        # Check all axes in the figure for title/label ownership
        figure = artist.figure
        check_axes = [axes] if axes is not None else []
        if figure is not None:
            check_axes = list(figure.axes)
        for ax in check_axes:
            if artist is ax.title:
                return "ax.set_title()"
            if artist is ax.xaxis.label:
                return "ax.set_xlabel()"
            if artist is ax.yaxis.label:
                return "ax.set_ylabel()"
        return "ax.text()"

    if isinstance(artist, Line2D):
        return _infer_line_call(artist)

    if isinstance(artist, PathCollection):
        return "ax.scatter()"

    if isinstance(artist, PolyCollection):
        cls_name = type(artist).__name__
        if "FillBetween" in cls_name:
            return "ax.fill_between() / ax.fill_betweenx()"
        return "ax.fill() / ax.pcolormesh()"

    if isinstance(artist, LineCollection):
        return "ax.vlines() / ax.hlines() / ax.eventplot()"

    if QuadMesh is not None and isinstance(artist, QuadMesh):
        return "ax.pcolormesh() / ax.pcolor()"

    if isinstance(artist, AxesImage):
        return "ax.imshow()"

    if isinstance(artist, Wedge):
        return "ax.pie()"

    if isinstance(artist, Rectangle):
        return _infer_rectangle_call(artist)

    if isinstance(artist, FancyArrowPatch):
        return "ax.annotate() [arrow]"

    if isinstance(artist, Spine):
        return f"ax.spines['{artist.spine_type}']"

    if isinstance(artist, Legend):
        return "ax.legend()"

    if isinstance(artist, Patch):
        return "ax.add_patch()"

    if isinstance(artist, Collection):
        return "ax.add_collection()"

    return None


def _infer_line_call(line: Line2D) -> str:
    """Distinguish ax.plot from ax.axhline, ax.axvline, etc."""
    axes = line.axes
    if axes is None:
        return "ax.plot()"

    xdata = line.get_xdata(orig=False)
    ydata = line.get_ydata(orig=False)

    if len(xdata) == 2:
        # axhline produces a line spanning [0, 1] in axes transform
        transform = line.get_transform()
        ax_trans = axes.get_yaxis_transform()
        if transform is ax_trans or (hasattr(transform, '_a') and hasattr(transform, '_b')):
            if ydata[0] == ydata[1]:
                return "ax.axhline()"
            if xdata[0] == xdata[1]:
                return "ax.axvline()"

    return "ax.plot()"


def _infer_rectangle_call(rect: Rectangle) -> str:
    """Distinguish bar rectangles from axhspan/axvspan and manual patches."""
    axes = getattr(rect, "axes", None)
    if axes is None:
        return "ax.add_patch(Rectangle(...))"

    # Check if part of a bar container
    for container in axes.containers:
        if isinstance(container, BarContainer) and rect in container.patches:
            return "ax.bar() / ax.barh()"

    # axhspan/axvspan create rectangles that span [0,1] in one dimension
    # in axes-relative coords
    x, y = rect.get_x(), rect.get_y()
    w, h = rect.get_width(), rect.get_height()

    if x == 0 and w == 1:
        return "ax.axhspan()"
    if y == 0 and h == 1:
        return "ax.axvspan()"

    return "ax.add_patch(Rectangle(...))"
