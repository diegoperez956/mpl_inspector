from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from matplotlib.artist import Artist
from matplotlib.collections import PathCollection
from matplotlib.lines import Line2D
from matplotlib.patches import PathPatch, Rectangle


@dataclass(slots=True)
class HighlightStyle:
    color: str
    alpha: float = 0.9
    linewidth: float = 2.0
    zorder_boost: float = 1_000.0


@dataclass(slots=True)
class HighlightHandle:
    artists: list[Artist] = field(default_factory=list)

    def remove(self) -> None:
        for artist in self.artists:
            try:
                artist.remove()
            except (ValueError, AttributeError):
                continue
        self.artists.clear()


def create_highlight(
    artist: Artist,
    *,
    style: HighlightStyle,
    renderer: Any | None = None,
) -> HighlightHandle | None:
    if getattr(artist, "_mpl_inspector_internal", False):
        return None

    if isinstance(artist, Line2D):
        return _highlight_line(artist, style=style)

    if isinstance(artist, PathCollection):
        return _highlight_collection(artist, style=style)

    if hasattr(artist, "get_path") and hasattr(artist, "get_transform"):
        return _highlight_patch_like(artist, style=style)

    return _highlight_bbox(artist, style=style, renderer=renderer)


def _highlight_line(artist: Line2D, *, style: HighlightStyle) -> HighlightHandle:
    axes = artist.axes
    if axes is None:
        return HighlightHandle()

    highlight = Line2D(
        artist.get_xdata(orig=False),
        artist.get_ydata(orig=False),
        color=style.color,
        linewidth=max(float(artist.get_linewidth()) + style.linewidth, style.linewidth),
        linestyle=artist.get_linestyle(),
        marker=artist.get_marker(),
        markersize=max(float(artist.get_markersize()) + 2.0, 6.0),
        markerfacecolor="none",
        markeredgecolor=style.color,
        alpha=style.alpha,
        zorder=artist.get_zorder() + style.zorder_boost,
    )
    highlight.set_transform(artist.get_transform())
    highlight.set_clip_box(artist.get_clip_box())
    _apply_clip(highlight, artist)
    _mark_internal(highlight)
    axes.add_line(highlight)
    return HighlightHandle([highlight])


def _highlight_collection(
    artist: PathCollection,
    *,
    style: HighlightStyle,
) -> HighlightHandle:
    axes = artist.axes
    if axes is None:
        return HighlightHandle()

    offsets = np.asarray(artist.get_offsets())
    if offsets.size == 0:
        return HighlightHandle()

    sizes = np.asarray(artist.get_sizes(), dtype=float)
    if sizes.size == 0:
        sizes = np.full(len(offsets), 36.0)
    else:
        sizes = np.maximum(sizes, 18.0) * 1.25

    highlight = axes.scatter(
        offsets[:, 0],
        offsets[:, 1],
        s=sizes,
        facecolors="none",
        edgecolors=style.color,
        linewidths=style.linewidth,
        alpha=style.alpha,
        zorder=artist.get_zorder() + style.zorder_boost,
    )
    highlight.set_transform(artist.get_transform())
    highlight.set_paths(artist.get_paths())
    offset_transform = getattr(artist, "get_offset_transform", lambda: None)()
    if offset_transform is not None:
        try:
            highlight.set_offset_transform(offset_transform)
        except AttributeError:
            highlight.set_transOffset(offset_transform)
    _apply_clip(highlight, artist)
    _mark_internal(highlight)
    return HighlightHandle([highlight])


def _highlight_patch_like(artist: Artist, *, style: HighlightStyle) -> HighlightHandle | None:
    axes = getattr(artist, "axes", None)
    if axes is None:
        return None

    try:
        path = artist.get_path()
        transform = artist.get_transform()
    except Exception:
        return None

    overlay = PathPatch(
        path,
        transform=transform,
        facecolor="none",
        edgecolor=style.color,
        linewidth=max(_get_linewidth(artist) + style.linewidth, style.linewidth),
        linestyle="-",
        alpha=style.alpha,
        zorder=artist.get_zorder() + style.zorder_boost,
    )
    overlay.set_clip_box(artist.get_clip_box())
    _apply_clip(overlay, artist)
    _mark_internal(overlay)
    axes.add_patch(overlay)
    return HighlightHandle([overlay])


def _highlight_bbox(
    artist: Artist,
    *,
    style: HighlightStyle,
    renderer: Any | None = None,
) -> HighlightHandle | None:
    figure = artist.figure
    if figure is None or renderer is None:
        return None

    try:
        bbox = artist.get_window_extent(renderer=renderer)
    except Exception:
        return None
    if bbox is None or bbox.width <= 0 or bbox.height <= 0:
        return None

    figure_bbox = bbox.transformed(figure.transFigure.inverted())
    rectangle = Rectangle(
        (figure_bbox.x0, figure_bbox.y0),
        figure_bbox.width,
        figure_bbox.height,
        transform=figure.transFigure,
        fill=False,
        edgecolor=style.color,
        linewidth=style.linewidth,
        linestyle=(0, (4, 2)),
        alpha=style.alpha,
        zorder=style.zorder_boost,
    )
    _mark_internal(rectangle)
    figure.add_artist(rectangle)
    return HighlightHandle([rectangle])


def _get_linewidth(artist: Artist) -> float:
    getter = getattr(artist, "get_linewidth", None)
    if getter is None:
        return 1.0
    try:
        value = float(getter())
    except (TypeError, ValueError):
        return 1.0
    return value


def _apply_clip(target: Artist, source: Artist) -> None:
    clip_path = source.get_clip_path()
    if clip_path is None:
        return
    try:
        target.set_clip_path(clip_path)
    except TypeError:
        try:
            target.set_clip_path(*clip_path)
        except Exception:
            return


def _mark_internal(artist: Artist) -> None:
    artist._mpl_inspector_internal = True
    artist.set_gid("mpl-inspector-internal")
    artist.set_picker(False)
