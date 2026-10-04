"""Headless, JSON-ready description of a Matplotlib figure.

``snapshot(fig)`` needs no GUI and no event loop; it works on the Agg
backend. The returned dict follows the schema documented in ``AGENT.md``
(``schema_version`` bumps on breaking changes). Every number is a plain
Python float/int and non-finite values become ``None``, so
``json.dumps(snapshot(fig))`` always yields valid JSON.

Coordinates:

* ``bbox_display`` — ``[x0, y0, x1, y1]`` in pixels at ``fig.dpi``, origin
  at the *bottom-left* of the figure (Matplotlib display coordinates).
* ``bbox_data`` — the same box mapped into the owning axes' data
  coordinates.
* ``bbox_figure`` — figure-fraction coordinates (0..1).
"""

from __future__ import annotations

from typing import Any, Iterator

import numpy as np
from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.collections import Collection, PathCollection
from matplotlib.colors import to_hex, to_rgba_array
from matplotlib.figure import Figure
from matplotlib.image import AxesImage
from matplotlib.legend import Legend
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.text import Text
from matplotlib.transforms import Bbox

from .adapters import _is_internal, _normalize_label
from .containers import find_container
from .provenance import infer_call

SCHEMA_VERSION = "1"

_MAX_COLORS = 12


def snapshot(fig: Figure) -> dict[str, Any]:
    """Return a JSON-serializable description of *fig* and everything in it."""
    renderer = get_renderer(fig)
    width, height = fig.get_size_inches()
    suptitle = getattr(fig, "_suptitle", None)
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "Figure",
        "size_inches": [_num(width), _num(height)],
        "dpi": _num(fig.dpi),
        "size_px": [_num(fig.bbox.width), _num(fig.bbox.height)],
        "facecolor": _hex(fig.get_facecolor()),
        "suptitle": suptitle.get_text() if suptitle is not None else None,
        "layout_engine": layout_engine_name(fig),
        "texts": [
            _text_record(text, f"fig.t{index}", None, renderer)
            for index, text in enumerate(fig.texts)
            if not _is_internal(text)
        ],
        "legends": [_legend_record(legend, None, renderer) for legend in fig.legends],
        "axes": [_axes_record(ax, renderer) for ax in fig.axes],
    }


def get_renderer(fig: Figure) -> Any:
    """Draw *fig* once (finalizing layout and ticks) and return its renderer."""
    fig.canvas.draw()
    getter = getattr(fig.canvas, "get_renderer", None)
    if getter is not None:
        return getter()
    return fig._get_renderer()  # non-Agg canvases


def iter_axes_artists(ax: Axes) -> Iterator[Artist]:
    """Yield the user-level artists drawn in *ax*, in a stable order.

    Titles, axis labels, ticks, spines and the legend are reported on the
    axes record instead of here.
    """
    groups = (ax.lines, ax.collections, ax.patches, ax.images, ax.texts, ax.artists, ax.tables)
    for group in groups:
        for artist in group:
            if artist is ax.patch or _is_internal(artist):
                continue
            yield artist


def artist_ids(fig: Figure) -> dict[int, str]:
    """Map ``id(artist)`` to the snapshot id (``"ax0.3"``) for every artist."""
    ids: dict[int, str] = {}
    for ax_index, ax in enumerate(fig.axes):
        for index, artist in enumerate(iter_axes_artists(ax)):
            ids[id(artist)] = f"ax{ax_index}.{index}"
    return ids


def layout_engine_name(fig: Figure) -> str | None:
    engine = fig.get_layout_engine()
    if engine is None:
        return None
    name = type(engine).__name__.removesuffix("LayoutEngine").lower()
    return name or None


def axis_units(axis: Any) -> str | None:
    """Return ``"category"``, ``"date"``, another converter name, or ``None``."""
    getter = getattr(axis, "get_converter", None)
    converter = getter() if getter is not None else getattr(axis, "converter", None)
    if converter is None:
        return None
    module = type(converter).__module__
    if module.endswith("category"):
        return "category"
    if module.endswith("dates"):
        return "date"
    return type(converter).__name__


def is_colorbar_axes(ax: Axes) -> bool:
    return hasattr(ax, "_colorbar") or ax.get_label() == "<colorbar>"


def _axes_record(ax: Axes, renderer: Any) -> dict[str, Any]:
    index = ax.figure.axes.index(ax)
    ax_id = f"ax{index}"
    bbox = ax.get_window_extent(renderer)
    legend = ax.get_legend()
    return {
        "id": ax_id,
        "index": index,
        "visible": ax.get_visible(),
        "axis_on": bool(ax.axison),
        "is_colorbar": is_colorbar_axes(ax),
        "title": ax.get_title(),
        "xlabel": ax.get_xlabel(),
        "ylabel": ax.get_ylabel(),
        "xaxis": _axis_record(ax, "x"),
        "yaxis": _axis_record(ax, "y"),
        "aspect": ax.get_aspect() if isinstance(ax.get_aspect(), str) else _num(ax.get_aspect()),
        "facecolor": _hex(ax.get_facecolor()),
        "bbox_display": _bbox(bbox),
        "bbox_figure": _bbox(ax.get_position()),
        "legend": _legend_record(legend, ax, renderer) if isinstance(legend, Legend) else None,
        "artists": [
            _artist_record(artist, f"{ax_id}.{artist_index}", ax, renderer)
            for artist_index, artist in enumerate(iter_axes_artists(ax))
        ],
    }


def _axis_record(ax: Axes, which: str) -> dict[str, Any]:
    axis = ax.xaxis if which == "x" else ax.yaxis
    low, high = ax.get_xlim() if which == "x" else ax.get_ylim()
    shared = ax.get_shared_x_axes() if which == "x" else ax.get_shared_y_axes()
    siblings = [other for other in shared.get_siblings(ax) if other is not ax and other in ax.figure.axes]
    return {
        "label": axis.get_label_text(),
        "scale": axis.get_scale(),
        "lim": [_num(low), _num(high)],
        "inverted": bool(axis.get_inverted()),
        "units": axis_units(axis),
        "shared_with": sorted(f"ax{ax.figure.axes.index(other)}" for other in siblings),
    }


def _legend_record(legend: Legend, ax: Axes | None, renderer: Any) -> dict[str, Any]:
    return {
        "visible": legend.get_visible(),
        "entries": [text.get_text() for text in legend.get_texts()],
        "bbox_display": _bbox(_extent(legend, renderer)),
        "bbox_data": _bbox(_to_data(_extent(legend, renderer), ax)),
    }


def _text_record(text: Text, text_id: str, ax: Axes | None, renderer: Any) -> dict[str, Any]:
    record = _base_record(text, text_id, ax, renderer)
    record["text"] = text.get_text()
    record["fontsize"] = _num(text.get_fontsize())
    record["colors"] = {"color": _hex(text.get_color())}
    return record


def _artist_record(artist: Artist, artist_id: str, ax: Axes, renderer: Any) -> dict[str, Any]:
    if isinstance(artist, Text):
        return _text_record(artist, artist_id, ax, renderer)
    record = _base_record(artist, artist_id, ax, renderer)
    record["colors"] = _colors(artist)
    record["n_points"], record["data_extent"] = _data_summary(artist, ax)
    if isinstance(artist, Line2D):
        record["linewidth"] = _num(artist.get_linewidth())
        record["linestyle"] = artist.get_linestyle()
        record["marker"] = str(artist.get_marker())
    return record


def _base_record(artist: Artist, artist_id: str, ax: Axes | None, renderer: Any) -> dict[str, Any]:
    container = find_container(artist)
    bbox = _extent(artist, renderer)
    return {
        "id": artist_id,
        "type": type(artist).__name__,
        "call": infer_call(artist),
        "container": type(container).__name__ if container is not None else None,
        "label": _normalize_label(artist.get_label()) or None,
        "visible": artist.get_visible(),
        "alpha": _num(artist.get_alpha()),
        "zorder": _num(artist.get_zorder()),
        "clip_on": artist.get_clip_on(),
        "bbox_display": _bbox(bbox),
        "bbox_data": _bbox(_to_data(bbox, ax)),
        "n_points": None,
        "data_extent": None,
    }


def _colors(artist: Artist) -> dict[str, Any]:
    if isinstance(artist, Line2D):
        return {
            "color": _hex(artist.get_color()),
            "markerfacecolor": _hex(artist.get_markerfacecolor()),
            "markeredgecolor": _hex(artist.get_markeredgecolor()),
        }
    if isinstance(artist, Collection):
        colors = {
            "facecolors": _hex_list(artist.get_facecolor()),
            "edgecolors": _hex_list(artist.get_edgecolor()),
        }
        if artist.get_array() is not None:
            colors["cmap"] = artist.get_cmap().name
        return colors
    if isinstance(artist, Patch):
        return {"facecolor": _hex(artist.get_facecolor()), "edgecolor": _hex(artist.get_edgecolor())}
    if isinstance(artist, AxesImage):
        return {"cmap": artist.get_cmap().name}
    return {}


def _data_summary(artist: Artist, ax: Axes) -> tuple[int | None, dict[str, Any] | None]:
    """Return ``(n_points, {"x": [min, max], "y": [min, max]})`` in data coords."""
    if isinstance(artist, Line2D):
        xy = artist.get_xydata()
        if artist.get_transform() != ax.transData:  # e.g. axhline: axes coords
            return len(xy), None
        return len(xy), _xy_extent(xy)
    if isinstance(artist, PathCollection):
        offsets = np.asarray(artist.get_offsets())
        if artist.get_offset_transform() != ax.transData:
            return len(offsets), None
        return len(offsets), _xy_extent(offsets)
    if isinstance(artist, Collection):
        n_paths = len(artist.get_paths())
        try:
            lim = artist.get_datalim(ax.transData)
        except Exception:
            return n_paths, None
        return n_paths, _bbox_extent(lim)
    if isinstance(artist, AxesImage):
        left, right, bottom, top = artist.get_extent()
        return int(np.prod(artist.get_array().shape[:2])), {
            "x": [_num(min(left, right)), _num(max(left, right))],
            "y": [_num(min(bottom, top)), _num(max(bottom, top))],
        }
    if isinstance(artist, Patch) and artist.get_data_transform() == ax.transData:
        return None, _bbox_extent(artist.get_path().get_extents(artist.get_patch_transform()))
    return None, None


def _xy_extent(xy: Any) -> dict[str, Any] | None:
    array = np.asarray(xy, dtype=float)
    if array.ndim != 2 or array.shape[0] == 0:
        return None
    finite = array[np.isfinite(array).all(axis=1)]
    if finite.size == 0:
        return None
    return {
        "x": [_num(finite[:, 0].min()), _num(finite[:, 0].max())],
        "y": [_num(finite[:, 1].min()), _num(finite[:, 1].max())],
    }


def _bbox_extent(bbox: Bbox) -> dict[str, Any] | None:
    values = [bbox.x0, bbox.x1, bbox.y0, bbox.y1]
    if not np.isfinite(values).all():
        return None
    return {"x": [_num(bbox.xmin), _num(bbox.xmax)], "y": [_num(bbox.ymin), _num(bbox.ymax)]}


def _extent(artist: Artist, renderer: Any) -> Bbox | None:
    try:
        bbox = artist.get_window_extent(renderer)
    except Exception:
        bbox = None
    ax = getattr(artist, "axes", None)
    if (bbox is None or not np.isfinite(bbox.get_points()).all()) and isinstance(artist, Collection) and ax is not None:
        # Offset collections (scatter) report an empty window extent.
        # ponytail: marker centers only, marker size not included.
        try:
            bbox = artist.get_datalim(ax.transData).transformed(ax.transData)
        except Exception:
            return None
    if bbox is None or not np.isfinite(bbox.get_points()).all():
        return None
    return bbox


def _to_data(bbox: Bbox | None, ax: Axes | None) -> Bbox | None:
    if bbox is None or ax is None:
        return None
    try:
        return bbox.transformed(ax.transData.inverted())
    except Exception:
        return None


def _bbox(bbox: Bbox | None) -> list[float | None] | None:
    if bbox is None:
        return None
    values = [_num(value) for value in (bbox.x0, bbox.y0, bbox.x1, bbox.y1)]
    return None if None in values else values


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return round(number, 6)


def _hex(color: Any) -> str | None:
    """``#rrggbb`` for opaque colors, ``#rrggbbaa`` when translucent."""
    try:
        rgba = to_rgba_array(color)
    except (TypeError, ValueError):
        return None
    if len(rgba) == 0:
        return None
    return to_hex(rgba[0], keep_alpha=bool(rgba[0][3] < 1))


def _hex_list(colors: Any) -> list[str]:
    unique: list[str] = []
    for rgba in to_rgba_array(colors):
        value = to_hex(rgba, keep_alpha=bool(rgba[3] < 1))
        if value not in unique:
            unique.append(value)
        if len(unique) >= _MAX_COLORS:  # ponytail: preview only, enough to spot a palette
            break
    return unique
