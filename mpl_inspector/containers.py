"""Map individual artists back to their owning Matplotlib containers.

Matplotlib's high-level plotting functions (``bar``, ``errorbar``, ``stem``,
``contour``, etc.) return container objects that group the underlying artists.
This module provides ``find_container`` which, given a low-level artist like a
single ``Rectangle`` from a bar chart, returns the container it belongs to
(e.g. ``BarContainer``).  This powers the "what object made this?" provenance
feature.
"""

from __future__ import annotations

from typing import Any

from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.container import BarContainer, ErrorbarContainer, StemContainer

try:
    from matplotlib.contour import ContourSet
except ImportError:  # pragma: no cover
    ContourSet = None  # type: ignore[misc,assignment]


def find_container(artist: Artist) -> BarContainer | ErrorbarContainer | StemContainer | None:
    """Return the container that owns *artist*, or ``None``."""
    axes_obj: Any = getattr(artist, "axes", None)
    if not isinstance(axes_obj, Axes):
        return None

    for container in axes_obj.containers:
        if _artist_in_container(artist, container):
            return container

    return None


def find_contour_set(artist: Artist) -> Any | None:
    """Return the ContourSet that owns *artist*, or ``None``.

    ContourSets are not standard containers — they live in a private
    attribute on their child collections.
    """
    if ContourSet is None:
        return None

    # Matplotlib sets a back-reference on each collection in a ContourSet
    cs = getattr(artist, "_contour_set", None)
    if cs is not None and isinstance(cs, ContourSet):
        return cs

    # Fallback: walk axes._children or similar
    axes: Axes | None = getattr(artist, "axes", None)
    if axes is None:
        return None

    # Check all collections for ContourSet membership
    for child in axes.get_children():
        if isinstance(child, ContourSet):
            if hasattr(child, "collections") and artist in child.collections:
                return child
            # Newer matplotlib stores artists differently
            if hasattr(child, "allsegs"):
                for a in child.get_children() if hasattr(child, "get_children") else []:
                    if a is artist:
                        return child
    return None


def _artist_in_container(
    artist: Artist,
    container: BarContainer | ErrorbarContainer | StemContainer,
) -> bool:
    """Check if *artist* is a member of *container*."""
    if isinstance(container, BarContainer):
        if artist in container.patches:
            return True
        if container.errorbar is not None:
            return _artist_in_errorbar(artist, container.errorbar)
        return False

    if isinstance(container, ErrorbarContainer):
        return _artist_in_errorbar(artist, container)

    if isinstance(container, StemContainer):
        if artist is container.markerline:
            return True
        if artist is container.stemlines:
            return True
        if artist is container.baseline:
            return True
        return False

    # Unknown container type — try iteration
    try:
        return artist in container  # type: ignore[operator]
    except TypeError:
        return False


def _artist_in_errorbar(artist: Artist, container: ErrorbarContainer) -> bool:
    data_line, cap_lines, bar_lines = container
    if artist is data_line:
        return True
    if cap_lines and artist in cap_lines:
        return True
    if bar_lines and artist in bar_lines:
        return True
    return False
