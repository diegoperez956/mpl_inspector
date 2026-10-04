"""Actionable diagnostics for Matplotlib figures.

``lint(fig)`` draws the figure headlessly and returns a list of plain dicts::

    {
        "code": "tick-label-overlap",       # stable, machine-readable
        "severity": "error",                # error | warning | info
        "message": "6 of 12 x tick labels on ax0 overlap each other",
        "fix": "ax.tick_params(axis='x', labelrotation=45) ...",
        "location": {"axes": 0, "target": "ax0.xticklabels", "bbox_display": [...]},
    }

``location.target`` uses the same ids as ``snapshot()`` (``ax0``,
``ax0.3``, ``ax0.title``, ``fig.suptitle`` ...). ``bbox_display`` is in
pixels at ``fig.dpi`` with the origin at the bottom-left.
"""

from __future__ import annotations

import copy
import itertools
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

import numpy as np
from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.collections import Collection, PathCollection
from matplotlib.colors import to_hex, to_rgba, to_rgba_array
from matplotlib.container import BarContainer
from matplotlib.figure import Figure
from matplotlib.image import AxesImage
from matplotlib.legend import Legend
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Wedge
from matplotlib.text import Text
from matplotlib.transforms import Bbox

from .adapters import _is_internal
from .snapshot import (
    _bbox,
    _extent,
    artist_ids,
    axis_units,
    figure_texts,
    get_renderer,
    is_colorbar_axes,
    iter_axes_artists,
    layout_engine_name,
    root_figure,
)

SEVERITIES = ("error", "warning", "info")

#: Every diagnostic code with its severity and what it means.
CODES: dict[str, tuple[str, str]] = {
    "tick-label-overlap": ("error", "Tick labels on one axis overlap each other."),
    "text-overlap": ("error", "Two text elements (titles, labels, annotations, tick labels) overlap."),
    "text-cut-off": ("error", "Text extends past the figure edge and is cut off in the saved image."),
    "artist-outside-limits": ("error", "A data artist lies entirely outside the axes view limits."),
    "axes-overlap": ("error", "Two axes overlap and neither is an inset of the other."),
    "axes-collapsed": ("error", "An axes has (almost) zero width or height."),
    "data-clipped": ("info", "Some points of a data artist are outside the view limits or invalid for the scale."),
    "legend-covers-data": ("warning", "The legend box sits on top of plotted data."),
    "missing-axis-label": ("warning", "An axis with data and visible tick labels has no label."),
    "missing-title": ("info", "An axes has no title and the figure has no suptitle."),
    "small-font": ("warning", "Text is smaller than the minimum readable font size."),
    "low-contrast": ("warning", "Text or data marks have too little contrast against their background."),
    "colorblind-unsafe": ("warning", "Two series colors are hard to tell apart with color-vision deficiency."),
    "rainbow-colormap": ("warning", "A rainbow colormap (jet, hsv, ...) distorts data and is not colorblind-safe."),
    "empty-axes": ("warning", "A visible axes contains no data."),
    "too-many-categories": ("warning", "Too many legend entries, categories or pie wedges to read."),
    "inconsistent-scales": ("warning", "Axes with the same axis label use different scales or units."),
    "unshared-limits": ("info", "Axes with the same axis label show different ranges without sharing."),
    "layout-warning": ("warning", "Matplotlib's layout engine reported a problem."),
    "runtime-warning": ("info", "A Python/Matplotlib warning was emitted while running or drawing."),
    "script-error": ("error", "The plotting script raised an exception (CLI only)."),
    "no-figures": ("error", "The script finished without creating any figure (CLI only)."),
}

MIN_FONTSIZE = 8.0
MIN_TEXT_CONTRAST = 3.0
MIN_MARK_CONTRAST = 1.5
MAX_LEGEND_ENTRIES = 10
MAX_CATEGORIES = 20
MAX_PIE_WEDGES = 8
RAINBOW_CMAPS = {"jet", "hsv", "rainbow", "gist_rainbow", "nipy_spectral", "gist_ncar", "flag", "prism"}

_WHITE = np.ones(3)
_CONSTRAINED_FIX = "fig.set_layout_engine('constrained') (or plt.subplots(..., layout='constrained'))"


def lint(fig: Figure, *, min_fontsize: float = MIN_FONTSIZE) -> list[dict[str, Any]]:
    """Return diagnostics for *fig*, most severe first."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        renderer = get_renderer(fig)
    ctx = _Ctx(fig, renderer, artist_ids(fig), min_fontsize)
    found: list[dict[str, Any]] = warning_diagnostics(caught)
    for check in _CHECKS:
        found.extend(check(ctx))
    return sorted(found, key=lambda d: SEVERITIES.index(d["severity"]))


def warning_diagnostics(caught: Iterable[warnings.WarningMessage]) -> list[dict[str, Any]]:
    """Turn recorded warnings into diagnostics (deduplicated by message)."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in caught:
        message = str(record.message)
        if message in seen or "non-interactive" in message:
            continue
        seen.add(message)
        if "layout" in message.lower():
            found.append(_diag("layout-warning", message, f"Try {_CONSTRAINED_FIX}; if it still fails, enlarge the figure or shorten labels."))
        else:
            where = f"{record.category.__name__} at {Path(record.filename).name}:{record.lineno}"
            found.append(_diag("runtime-warning", f"{message} ({where})", "read the warning text; it usually names the offending call or argument"))
    return found


# --------------------------------------------------------------------------- context


@dataclass
class _TextEl:
    target: str
    group: str  # tick labels of one axis share a group; other texts are their own group
    text: Text
    bbox: Bbox  # axis-aligned extent
    corners: np.ndarray  # 4x2 rotated rectangle actually covered by the text
    ax: Axes | None


class _Ctx:
    def __init__(self, fig: Figure, renderer: Any, ids: dict[int, str], min_fontsize: float) -> None:
        self.fig = fig
        self.renderer = renderer
        self.ids = ids
        self.min_fontsize = min_fontsize
        self.layout = layout_engine_name(fig)
        self.axes = [ax for ax in fig.axes if ax.get_visible()]
        self.texts = list(self._collect_texts())

    def ax_id(self, ax: Axes) -> str:
        return f"ax{_ax_index(ax)}"

    def artist_id(self, artist: Artist) -> str:
        return self.ids.get(id(artist), type(artist).__name__)

    def layout_fix(self) -> str:
        if self.layout is None:
            return _CONSTRAINED_FIX
        return f"the '{self.layout}' layout engine is already on: shorten the text, reduce its fontsize, or enlarge the figure (fig.set_size_inches)"

    def _collect_texts(self) -> Iterator[_TextEl]:
        fig = self.fig
        for target, text in figure_texts(fig):
            yield from self._text_el(text, target, None)
        for ax in self.axes:
            ax_id = self.ax_id(ax)
            yield from self._text_el(ax.title, f"{ax_id}.title", ax)
            yield from self._text_el(getattr(ax, "_left_title", None), f"{ax_id}.title_left", ax)
            yield from self._text_el(getattr(ax, "_right_title", None), f"{ax_id}.title_right", ax)
            for text in ax.texts:
                yield from self._text_el(text, self.artist_id(text), ax)
            if not ax.axison:
                continue
            for which, axis in (("x", ax.xaxis), ("y", ax.yaxis)):
                if not axis.get_visible():
                    continue
                yield from self._text_el(axis.label, f"{ax_id}.{which}label", ax)
                group = f"{ax_id}.{which}ticklabels"
                for index, label in enumerate(_tick_labels(axis)):
                    for el in self._text_el(label, f"{group}[{index}]", ax):
                        el.group = group
                        yield el

    def _text_el(self, text: Text | None, target: str, ax: Axes | None) -> Iterator[_TextEl]:
        if text is None or _is_internal(text) or not text.get_visible() or not text.get_text().strip():
            return
        bbox = _extent(text, self.renderer)
        if bbox is None or bbox.width <= 0 or bbox.height <= 0:
            return
        yield _TextEl(target, target, text, bbox, _text_corners(text, bbox, self.renderer), ax)


def _text_corners(text: Text, bbox: Bbox, renderer: Any) -> np.ndarray:
    """Corners of the rotated text box; its center is always the extent's center."""
    angle = np.deg2rad(text.get_rotation())
    if np.isclose(np.sin(2 * angle), 0):  # 0/90/180/270: the extent is exact
        return _bbox_corners(bbox)
    flat = copy.copy(text)  # measure unrotated size without touching the real artist
    flat.stale_callback = None
    flat.set_rotation(0)
    layout = _extent(flat, renderer)
    if layout is None:
        return _bbox_corners(bbox)
    cos, sin = np.cos(angle), np.sin(angle)
    half = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]]) * [layout.width / 2, layout.height / 2]
    rotated = half @ np.array([[cos, sin], [-sin, cos]])
    return rotated + [(bbox.x0 + bbox.x1) / 2, (bbox.y0 + bbox.y1) / 2]


def _bbox_corners(bbox: Bbox) -> np.ndarray:
    return np.array([[bbox.x0, bbox.y0], [bbox.x1, bbox.y0], [bbox.x1, bbox.y1], [bbox.x0, bbox.y1]])


def _polygons_overlap(a: np.ndarray, b: np.ndarray, min_px: float = 1.0) -> bool:
    """Separating-axis test for two convex quads; overlap must exceed *min_px*."""
    for poly in (a, b):
        for edge in np.diff(np.vstack([poly, poly[:1]]), axis=0)[:2]:
            normal = np.array([-edge[1], edge[0]])
            length = np.hypot(*normal)
            if length == 0:
                continue
            pa, pb = a @ normal / length, b @ normal / length
            if min(pa.max(), pb.max()) - max(pa.min(), pb.min()) <= min_px:
                return False
    return True


def _tick_labels(axis: Any) -> Iterator[Text]:
    """Major tick labels that are actually drawn (inside the view interval)."""
    low, high = sorted(axis.get_view_interval())
    tolerance = (high - low) * 1e-9
    for tick in axis.get_major_ticks():
        loc = tick.get_loc()
        if loc is None or not (low - tolerance <= loc <= high + tolerance):
            continue
        for label in (tick.label1, tick.label2):
            if label.get_visible():
                yield label


def _diag(
    code: str,
    message: str,
    fix: str,
    *,
    ax: int | None = None,
    target: str | None = None,
    bbox: Bbox | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": CODES[code][0],
        "message": message,
        "fix": fix,
        "location": {"axes": ax, "target": target, "bbox_display": _bbox(bbox)},
    }


def _ax_index(ax: Axes | None) -> int | None:
    return None if ax is None else root_figure(ax).axes.index(ax)


def _overlaps(a: Bbox, b: Bbox, min_px: float = 1.0) -> bool:
    width = min(a.x1, b.x1) - max(a.x0, b.x0)
    height = min(a.y1, b.y1) - max(a.y0, b.y0)
    return width > min_px and height > min_px


def _contains(outer: Bbox, inner: Bbox, tolerance: float = 1.0) -> bool:
    return (
        inner.x0 >= outer.x0 - tolerance
        and inner.y0 >= outer.y0 - tolerance
        and inner.x1 <= outer.x1 + tolerance
        and inner.y1 <= outer.y1 + tolerance
    )


def _data_artists(ax: Axes) -> list[Artist]:
    return [a for a in iter_axes_artists(ax) if a.get_visible() and not isinstance(a, Text)]


def _plot_axes(ctx: _Ctx) -> list[Axes]:
    """Visible, non-colorbar axes that hold data."""
    return [ax for ax in ctx.axes if not is_colorbar_axes(ax) and _data_artists(ax)]


def _quote(text: Text) -> str:
    value = text.get_text().strip().replace("\n", " ")
    return repr(value if len(value) <= 40 else value[:37] + "...")


def _label_of(ctx: _Ctx, artist: Artist) -> str:
    label = artist.get_label()
    name = ctx.artist_id(artist)
    return f"{name} {label!r}" if label and not label.startswith("_") else name


# --------------------------------------------------------------------------- text checks


def _check_text_overlap(ctx: _Ctx) -> Iterator[dict[str, Any]]:
    # ponytail: O(n^2) over visible texts; fine for a few hundred labels.
    tick_hits: dict[str, list[_TextEl]] = {}
    pair_hits: dict[tuple[str, str], tuple[_TextEl, _TextEl]] = {}
    for a, b in itertools.combinations(ctx.texts, 2):
        if not _overlaps(a.bbox, b.bbox) or not _polygons_overlap(a.corners, b.corners):
            continue
        if a.group == b.group:  # same tick axis
            tick_hits.setdefault(a.group, []).extend((a, b))
            continue
        key = tuple(sorted((a.group, b.group)))
        pair_hits.setdefault(key, (a, b))  # type: ignore[arg-type]

    for group, hits in tick_hits.items():
        unique = {el.target: el for el in hits}
        total = sum(1 for el in ctx.texts if el.group == group)
        which = "x" if group.endswith(".xticklabels") else "y"
        ax = unique[next(iter(unique))].ax
        if which == "x":
            fix = (
                "rotate: ax.tick_params(axis='x', labelrotation=45) + plt.setp(ax.get_xticklabels(), ha='right') "
                "(fig.autofmt_xdate() for dates); or fewer ticks (matplotlib.ticker.MaxNLocator), a smaller labelsize, "
                "a wider figure; long category names read best on ax.barh"
            )
        else:
            fix = (
                "fewer ticks via ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(6)), "
                "ax.tick_params(axis='y', labelsize=8), or a taller figure"
            )
        yield _diag(
            "tick-label-overlap",
            f"{len(unique)} of {total} {which} tick labels on {ctx.ax_id(ax)} overlap each other",
            fix,
            ax=_ax_index(ax),
            target=group,
            bbox=Bbox.union([el.bbox for el in unique.values()]),
        )

    crossing: list[tuple[str, str, Bbox, Axes | None]] = []
    for a, b in pair_hits.values():
        if a.ax is not b.ax:  # different subplots (or a subplot vs the figure): a layout problem
            crossing.append((a.target, b.target, Bbox.intersection(a.bbox, b.bbox), a.ax or b.ax))
            continue
        yield _diag(
            "text-overlap",
            f"{_quote(a.text)} ({a.target}) overlaps {_quote(b.text)} ({b.target})",
            "move one of them (x/y or xytext position), shorten it, or reduce its fontsize",
            ax=_ax_index(a.ax),
            target=a.target,
            bbox=Bbox.intersection(a.bbox, b.bbox),
        )
    for el in ctx.texts:  # text running into (or hidden under) another subplot
        for ax in ctx.axes:
            if ax is el.ax or not _overlaps(el.bbox, ax.bbox) or not _polygons_overlap(el.corners, _bbox_corners(ax.bbox)):
                continue
            if el.ax is not None and (_contains(ax.bbox, el.ax.bbox) or _contains(el.ax.bbox, ax.bbox)):
                continue  # twin or inset of the text's own axes
            crossing.append((el.target, ctx.ax_id(ax), Bbox.intersection(el.bbox, ax.bbox), ax))
    if crossing:
        examples = ", ".join(f"{a}/{b}" for a, b, _, _ in crossing[:5])
        more = f" and {len(crossing) - 5} more" if len(crossing) > 5 else ""
        yield _diag(
            "text-overlap",
            f"{len(crossing)} overlaps between text and other subplots: {examples}{more}",
            ctx.layout_fix(),
            ax=_ax_index(crossing[0][3]),
            target=crossing[0][0],
            bbox=Bbox.union([box for _, _, box, _ in crossing]),
        )


def _check_text_cut_off(ctx: _Ctx) -> Iterator[dict[str, Any]]:
    fig_box = ctx.fig.bbox
    cut: dict[str, list[_TextEl]] = {}
    for el in ctx.texts:
        low, high = el.corners.min(axis=0), el.corners.max(axis=0)
        if not _contains(fig_box, Bbox([low, high])):
            cut.setdefault(el.group, []).append(el)
    fix = ctx.layout_fix()
    if ctx.layout is None:
        fix += ", or fig.tight_layout() after plotting; when saving, savefig(..., bbox_inches='tight')"
    if len(cut) > 5:  # a figure-wide layout problem: one diagnostic, not one per label
        groups = list(cut)
        yield _diag(
            "text-cut-off",
            f"{len(groups)} text elements extend past the figure edge: {', '.join(groups[:5])} and {len(groups) - 5} more",
            fix,
            target=groups[0],
            bbox=Bbox.union([el.bbox for els in cut.values() for el in els]),
        )
        return
    for group, els in cut.items():
        first = els[0]
        if group == first.target:
            what = f"{_quote(first.text)} ({group}) extends past the figure edge and is cut off"
        else:
            what = f"{len(els)} tick labels ({group}) extend past the figure edge and are cut off"
        yield _diag(
            "text-cut-off",
            what,
            fix,
            ax=_ax_index(first.ax),
            target=group,
            bbox=Bbox.union([el.bbox for el in els]),
        )


def _check_small_font(ctx: _Ctx) -> Iterator[dict[str, Any]]:
    small: dict[str, list[_TextEl]] = {}
    for el in ctx.texts:
        if el.text.get_fontsize() < ctx.min_fontsize:
            small.setdefault(el.group, []).append(el)
    for group, els in small.items():
        size = min(el.text.get_fontsize() for el in els)
        if group.endswith("ticklabels"):
            fix = f"ax.tick_params(labelsize={ctx.min_fontsize:g}) (or larger)"
        else:
            fix = f"pass fontsize={ctx.min_fontsize:g} or larger (or raise plt.rcParams['font.size'])"
        yield _diag(
            "small-font",
            f"{group} uses {size:g} pt text; minimum readable size is {ctx.min_fontsize:g} pt",
            fix,
            ax=_ax_index(els[0].ax),
            target=group,
            bbox=Bbox.union([el.bbox for el in els]),
        )


def _check_missing_labels(ctx: _Ctx) -> Iterator[dict[str, Any]]:
    fig = ctx.fig
    has_suptitle = getattr(fig, "_suptitle", None) is not None and fig._suptitle.get_text().strip()
    ticked = {el.group for el in ctx.texts if el.group.endswith("ticklabels")}
    for ax in _plot_axes(ctx):
        ax_id = ctx.ax_id(ax)
        index = _ax_index(ax)
        if all(isinstance(a, AxesImage) for a in _data_artists(ax)):
            continue  # ponytail: imshow pixel axes rarely need labels
        for which in ("x", "y"):
            axis = ax.xaxis if which == "x" else ax.yaxis
            if axis.get_label_text().strip() or f"{ax_id}.{which}ticklabels" not in ticked:
                continue
            if getattr(fig, f"_sup{which}label", None) is not None:
                continue
            shared = ax.get_shared_x_axes() if which == "x" else ax.get_shared_y_axes()
            if any(
                (other.get_xlabel() if which == "x" else other.get_ylabel()).strip()
                for other in shared.get_siblings(ax)
                if other is not ax
            ):
                continue
            yield _diag(
                "missing-axis-label",
                f"{ax_id} has no {which} axis label",
                f"ax.set_{which}label('<quantity> (<unit>)')",
                ax=index,
                target=f"{ax_id}.{which}label",
                bbox=ax.bbox,
            )
        if not has_suptitle and not any(ax.get_title(loc).strip() for loc in ("center", "left", "right")):
            yield _diag(
                "missing-title",
                f"{ax_id} has no title and the figure has no suptitle",
                "ax.set_title('<what the chart shows>') or fig.suptitle(...)",
                ax=index,
                target=f"{ax_id}.title",
                bbox=ax.bbox,
            )


# --------------------------------------------------------------------------- color checks


def _relative_luminance(rgb: np.ndarray) -> float:
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return float(linear @ [0.2126, 0.7152, 0.0722])


def contrast_ratio(fg: Any, bg: Any) -> float:
    """WCAG 2 contrast ratio between two opaque RGB colors (1..21)."""
    light, dark = sorted((_relative_luminance(np.asarray(fg)), _relative_luminance(np.asarray(bg))), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _over(color: Any, bg: np.ndarray, alpha: float | None = None) -> np.ndarray:
    rgba = to_rgba(color)
    a = rgba[3] if alpha is None else alpha
    return a * np.asarray(rgba[:3]) + (1 - a) * bg


def _figure_bg(fig: Figure) -> np.ndarray:
    return _over(fig.get_facecolor(), _WHITE)


def _axes_bg(ax: Axes) -> np.ndarray:
    bg = _figure_bg(ax.figure)
    return _over(ax.get_facecolor(), bg) if ax.patch.get_visible() else bg


def _check_low_contrast(ctx: _Ctx) -> Iterator[dict[str, Any]]:
    reported: set[str] = set()
    for el in ctx.texts:
        if el.group in reported:
            continue
        patch = el.text.get_bbox_patch()
        if patch is not None and patch.get_visible() and to_rgba(patch.get_facecolor())[3] > 0:
            bg = _over(patch.get_facecolor(), _figure_bg(ctx.fig))
        elif el.ax is not None and _contains(el.ax.bbox, el.bbox, tolerance=0):
            if _over_colormapped(el, ctx.renderer):
                continue  # ponytail: background is the data itself; per-pixel sampling if this misses real issues
            bg = _axes_bg(el.ax)
        else:
            bg = _figure_bg(ctx.fig)
        fg = _over(el.text.get_color(), bg, el.text.get_alpha())
        ratio = contrast_ratio(fg, bg)
        if ratio < MIN_TEXT_CONTRAST:
            reported.add(el.group)
            yield _diag(
                "low-contrast",
                f"{el.group} text {to_hex(fg)} on {to_hex(bg)} has contrast {ratio:.2f}:1 (< {MIN_TEXT_CONTRAST:g}:1)",
                "use a darker text color (e.g. color='black' / '#333333') or a lighter background",
                ax=_ax_index(el.ax),
                target=el.group,
                bbox=el.bbox,
            )

    for ax in _plot_axes(ctx):
        bg = _axes_bg(ax)
        for artist, color in _mark_colors(ax):
            fg = _over(color, bg, artist.get_alpha())
            ratio = contrast_ratio(fg, bg)
            if ratio < MIN_MARK_CONTRAST:
                yield _diag(
                    "low-contrast",
                    f"{_label_of(ctx, artist)} color {to_hex(fg)} on {to_hex(bg)} has contrast {ratio:.2f}:1 (< {MIN_MARK_CONTRAST:g}:1)",
                    "use a darker/more saturated color, raise alpha, or add an edgecolor",
                    ax=_ax_index(ax),
                    target=ctx.artist_id(artist),
                    bbox=_extent(artist, ctx.renderer),
                )


def _over_colormapped(el: _TextEl, renderer: Any) -> bool:
    """Is the text drawn on top of an image, mesh or other colormapped artist?"""
    for artist in _data_artists(el.ax):
        if isinstance(artist, (AxesImage, Collection)) and artist.get_array() is not None:
            extent = _extent(artist, renderer)
            if extent is not None and _overlaps(extent, el.bbox):
                return True
    return False


def _mark_colors(ax: Axes) -> Iterator[tuple[Artist, Any]]:
    """(artist, color) for single-color lines, scatters and bars in *ax*."""
    for artist in _data_artists(ax):
        if isinstance(artist, Line2D):
            if artist.get_linestyle() in ("None", " ", "") and artist.get_marker() in ("None", None, " ", ""):
                continue
            yield artist, artist.get_color()
        elif isinstance(artist, PathCollection) and artist.get_array() is None:
            colors = np.unique(to_rgba_array(artist.get_facecolor()), axis=0)
            if len(colors) == 1:
                yield artist, colors[0]
        elif isinstance(artist, Patch) and not isinstance(artist, Wedge):
            if artist.get_data_transform() == ax.transData and to_rgba(artist.get_facecolor())[3] > 0:
                yield artist, artist.get_facecolor()


# Machado, Oliveira & Fernandes (2009), severity 1.0, applied in linear RGB.
_CVD = {
    "protanopia": np.array([[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]]),
    "deuteranopia": np.array([[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]]),
    "tritanopia": np.array([[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]]),
}
_XYZ = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
_D65 = np.array([0.95047, 1.0, 1.08883])
CVD_MIN_DELTA_E = 12.0  # below this two simulated colors read as "the same"


def _linear(rgb: np.ndarray) -> np.ndarray:
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def _lab_from_linear(linear: np.ndarray) -> np.ndarray:
    xyz = (_XYZ @ np.clip(linear, 0, 1)) / _D65
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def cvd_delta_e(a: Any, b: Any) -> dict[str, float]:
    """CIE76 distance between two colors, normally and under each CVD simulation."""
    la, lb = _linear(np.asarray(to_rgba(a)[:3])), _linear(np.asarray(to_rgba(b)[:3]))
    result = {"normal": float(np.linalg.norm(_lab_from_linear(la) - _lab_from_linear(lb)))}
    for name, matrix in _CVD.items():
        result[name] = float(np.linalg.norm(_lab_from_linear(matrix @ la) - _lab_from_linear(matrix @ lb)))
    return result


def _check_colorblind(ctx: _Ctx) -> Iterator[dict[str, Any]]:
    for ax in _plot_axes(ctx):
        series: dict[str, Artist] = {}
        for artist, color in _mark_colors(ax):
            bars = next((c for c in ax.containers if isinstance(c, BarContainer) and artist in c.patches), None)
            if bars is not None and artist is not bars.patches[0]:
                continue  # one color per bar series
            series.setdefault(to_hex(color), artist)
        for (hex_a, a), (hex_b, b) in itertools.combinations(series.items(), 2):
            if _distinct_style(a, b):
                continue
            delta = cvd_delta_e(hex_a, hex_b)
            if delta["normal"] < CVD_MIN_DELTA_E:
                continue  # already similar for everyone; not a CVD-specific problem
            worst = min(("protanopia", "deuteranopia", "tritanopia"), key=delta.__getitem__)
            if delta[worst] < CVD_MIN_DELTA_E:
                yield _diag(
                    "colorblind-unsafe",
                    f"{_label_of(ctx, a)} ({hex_a}) and {_label_of(ctx, b)} ({hex_b}) look alike with {worst} (ΔE {delta[worst]:.1f})",
                    "plt.style.use('tableau-colorblind10') or pick Okabe-Ito colors; also vary linestyle/marker so color is not the only cue",
                    ax=_ax_index(ax),
                    target=ctx.artist_id(a),
                    bbox=ax.bbox,
                )

        for artist in _data_artists(ax):
            if isinstance(artist, (AxesImage, Collection)) and artist.get_array() is not None:
                name = artist.get_cmap().name.removesuffix("_r")
                if name in RAINBOW_CMAPS:
                    yield _diag(
                        "rainbow-colormap",
                        f"{_label_of(ctx, artist)} uses the {name!r} colormap",
                        "cmap='viridis' or 'cividis' for sequential data, 'RdBu_r'/'coolwarm' for diverging data",
                        ax=_ax_index(ax),
                        target=ctx.artist_id(artist),
                        bbox=_extent(artist, ctx.renderer),
                    )


def _distinct_style(a: Artist, b: Artist) -> bool:
    """Lines that differ in linestyle or marker are distinguishable without color."""
    if not (isinstance(a, Line2D) and isinstance(b, Line2D)):
        return False
    return (a.get_linestyle(), str(a.get_marker())) != (b.get_linestyle(), str(b.get_marker()))


# --------------------------------------------------------------------------- data/axes checks


def _check_legend(ctx: _Ctx) -> Iterator[dict[str, Any]]:
    for ax in ctx.axes:
        legend = ax.get_legend()
        if not isinstance(legend, Legend) or not legend.get_visible():
            continue
        box = _extent(legend, ctx.renderer)
        entries = len(legend.get_texts())
        if entries > MAX_LEGEND_ENTRIES:
            yield _diag(
                "too-many-categories",
                f"legend on {ctx.ax_id(ax)} has {entries} entries (> {MAX_LEGEND_ENTRIES})",
                "group minor series into 'Other', split into subplots (small multiples), or label lines directly with ax.annotate",
                ax=_ax_index(ax),
                target=f"{ctx.ax_id(ax)}.legend",
                bbox=box,
            )
        if box is None:
            continue
        covered = [_label_of(ctx, artist) for artist in _data_artists(ax) if _hits_box(artist, ax, box, ctx.renderer)]
        if covered:
            outside = "ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1), borderaxespad=0) with " + _CONSTRAINED_FIX
            best = legend._loc == 0  # 0 == 'best'
            fix = f"move it outside: {outside}" if best else f"ax.legend(loc='best'), or move it outside: {outside}"
            yield _diag(
                "legend-covers-data",
                f"legend on {ctx.ax_id(ax)} covers data of {', '.join(covered)}",
                fix,
                ax=_ax_index(ax),
                target=f"{ctx.ax_id(ax)}.legend",
                bbox=box,
            )


def _hits_box(artist: Artist, ax: Axes, box: Bbox, renderer: Any) -> bool:
    if isinstance(artist, Line2D):
        if artist.get_linestyle() not in ("None", " ", ""):
            path = artist.get_transform().transform_path(artist.get_path())
            return bool(path.intersects_bbox(box, filled=False))
        points = _display_points(artist)
        return points is not None and bool(_inside(points, box).any())
    if isinstance(artist, PathCollection):
        points = _display_points(artist)
        return points is not None and bool(_inside(points, box).any())
    if isinstance(artist, Patch) and artist.get_data_transform() == ax.transData:
        extent = _extent(artist, renderer)
        return extent is not None and _overlaps(extent, box)
    return False  # ponytail: fills/images under a legend are usually fine


def _display_points(artist: Artist) -> np.ndarray | None:
    """Data points in display coords; rows that the scale cannot show are NaN."""
    if isinstance(artist, Line2D):
        xy, transform = artist.get_xydata(), artist.get_transform()
    elif isinstance(artist, PathCollection):
        xy, transform = artist.get_offsets(), artist.get_offset_transform()
    else:
        return None
    xy = np.ma.filled(np.ma.asarray(xy, dtype=float), np.nan)
    if xy.ndim != 2 or len(xy) == 0:
        return None
    xy = xy[np.isfinite(xy).all(axis=1)]
    with np.errstate(all="ignore"):
        return transform.transform(xy)


def _inside(points: np.ndarray, box: Bbox, tolerance: float = 0.5) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return (
            (points[:, 0] >= box.x0 - tolerance)
            & (points[:, 0] <= box.x1 + tolerance)
            & (points[:, 1] >= box.y0 - tolerance)
            & (points[:, 1] <= box.y1 + tolerance)
        )


def _check_outside_limits(ctx: _Ctx) -> Iterator[dict[str, Any]]:
    for ax in _plot_axes(ctx):
        limits = f"xlim={_fmt(ax.get_xlim())}, ylim={_fmt(ax.get_ylim())}"
        for artist in _data_artists(ax):
            name = _label_of(ctx, artist)
            points = _display_points(artist)
            if points is not None:
                if len(points) == 0:
                    continue
                inside = int(_inside(points, ax.bbox).sum())
                if inside == 0:
                    yield _outside(ctx, ax, artist, f"all {len(points)} points of {name} are outside the view ({limits})")
                elif inside < len(points):
                    yield _diag(
                        "data-clipped",
                        f"{len(points) - inside} of {len(points)} points of {name} are outside the view or invalid for the {ax.get_xscale()}/{ax.get_yscale()} scale ({limits})",
                        "fine if you zoomed on purpose; otherwise ax.relim(); ax.autoscale_view(), widen ax.set_xlim/ax.set_ylim, or drop non-positive values on log axes",
                        ax=_ax_index(ax),
                        target=ctx.artist_id(artist),
                        bbox=ax.bbox,
                    )
                continue
            extent = _extent(artist, ctx.renderer)
            if extent is not None and _disjoint(extent, ax.bbox):
                yield _outside(ctx, ax, artist, f"{name} is entirely outside the view ({limits})")


def _outside(ctx: _Ctx, ax: Axes, artist: Artist, message: str) -> dict[str, Any]:
    return _diag(
        "artist-outside-limits",
        message,
        "ax.relim(); ax.autoscale_view() — or widen ax.set_xlim/ax.set_ylim to include the data (check for a wrong axis, units or transform)",
        ax=_ax_index(ax),
        target=ctx.artist_id(artist),
        bbox=ax.bbox,
    )


def _disjoint(a: Bbox, b: Bbox, tolerance: float = 0.5) -> bool:
    return a.x1 < b.x0 - tolerance or a.x0 > b.x1 + tolerance or a.y1 < b.y0 - tolerance or a.y0 > b.y1 + tolerance


def _fmt(pair: tuple[float, float]) -> str:
    return f"({pair[0]:.4g}, {pair[1]:.4g})"


def _check_empty_and_categories(ctx: _Ctx) -> Iterator[dict[str, Any]]:
    if not ctx.axes and not ctx.texts:
        yield _diag("empty-axes", "the figure has no axes", "plot into it (fig.add_subplot()) or do not create it", bbox=ctx.fig.bbox)
    for ax in ctx.axes:
        if is_colorbar_axes(ax):
            continue
        ax_id = ctx.ax_id(ax)
        artists = [a for a in iter_axes_artists(ax) if a.get_visible()]
        if not artists:
            if ax.axison:
                yield _diag(
                    "empty-axes",
                    f"{ax_id} is visible but contains no data",
                    "fig.delaxes(ax) for an unused subplot slot, plot into it, or ax.set_axis_off() if it is meant to be blank",
                    ax=_ax_index(ax),
                    target=ax_id,
                    bbox=ax.bbox,
                )
            continue
        wedges = sum(isinstance(a, Wedge) for a in artists)
        if wedges > MAX_PIE_WEDGES:
            yield _diag(
                "too-many-categories",
                f"pie on {ax_id} has {wedges} wedges (> {MAX_PIE_WEDGES})",
                "use a sorted horizontal bar chart (ax.barh) or group small slices into 'Other'",
                ax=_ax_index(ax),
                target=ax_id,
                bbox=ax.bbox,
            )
        for which, axis in (("x", ax.xaxis), ("y", ax.yaxis)):
            if axis_units(axis) != "category":
                continue
            count = len(axis.get_majorticklocs())
            if count > MAX_CATEGORIES:
                yield _diag(
                    "too-many-categories",
                    f"{which} axis of {ax_id} has {count} categories (> {MAX_CATEGORIES})",
                    "show the top N and group the rest into 'Other', or use ax.barh with a taller figure",
                    ax=_ax_index(ax),
                    target=f"{ax_id}.{which}axis",
                    bbox=ax.bbox,
                )


def _check_scales(ctx: _Ctx) -> Iterator[dict[str, Any]]:
    axes = _plot_axes(ctx)
    for a, b in itertools.combinations(axes, 2):
        for which in ("x", "y"):
            axis_a, axis_b = (a.xaxis, b.xaxis) if which == "x" else (a.yaxis, b.yaxis)
            label = axis_a.get_label_text().strip()
            if not label or label != axis_b.get_label_text().strip():
                continue
            pair = f"{ctx.ax_id(a)} and {ctx.ax_id(b)}"
            if axis_a.get_scale() != axis_b.get_scale() or axis_units(axis_a) != axis_units(axis_b):
                yield _diag(
                    "inconsistent-scales",
                    f"{pair} both label {which} as {label!r} but use {axis_a.get_scale()}/{axis_units(axis_a)} vs {axis_b.get_scale()}/{axis_units(axis_b)} scale/units",
                    f"use the same ax.set_{which}scale(...) and data units on both, or label them differently",
                    ax=_ax_index(b),
                    target=f"{ctx.ax_id(b)}.{which}axis",
                    bbox=b.bbox,
                )
                continue
            shared = a.get_shared_x_axes() if which == "x" else a.get_shared_y_axes()
            if shared.joined(a, b):
                continue
            lim_a = sorted(a.get_xlim() if which == "x" else a.get_ylim())
            lim_b = sorted(b.get_xlim() if which == "x" else b.get_ylim())
            if not np.allclose(lim_a, lim_b, rtol=0.05, atol=1e-12 + 0.05 * abs(lim_a[1] - lim_a[0])):
                yield _diag(
                    "unshared-limits",
                    f"{pair} both show {label!r} on {which} but with different ranges {_fmt(lim_a)} vs {_fmt(lim_b)}",
                    f"plt.subplots(..., share{which}=True) or ax.share{which}(other) so panels compare directly",
                    ax=_ax_index(b),
                    target=f"{ctx.ax_id(b)}.{which}axis",
                    bbox=b.bbox,
                )


def _check_layout(ctx: _Ctx) -> Iterator[dict[str, Any]]:
    for ax in ctx.axes:
        box = ax.bbox
        if box.width < 5 or box.height < 5:
            yield _diag(
                "axes-collapsed",
                f"{ctx.ax_id(ax)} is {box.width:.0f}x{box.height:.0f} px",
                "enlarge the figure, reduce the number of subplots, or shorten the labels that crowd it out; check layout-warning diagnostics",
                ax=_ax_index(ax),
                target=ctx.ax_id(ax),
                bbox=box,
            )
    for a, b in itertools.combinations(ctx.axes, 2):
        if not _overlaps(a.bbox, b.bbox) or _contains(a.bbox, b.bbox) or _contains(b.bbox, a.bbox):
            continue  # twins and insets sit inside their parent
        yield _diag(
            "axes-overlap",
            f"{ctx.ax_id(a)} and {ctx.ax_id(b)} overlap",
            f"{_CONSTRAINED_FIX}, or position axes with plt.subplots/GridSpec instead of fig.add_axes rectangles",
            ax=_ax_index(b),
            target=ctx.ax_id(b),
            bbox=Bbox.intersection(a.bbox, b.bbox),
        )


_CHECKS = (
    _check_text_overlap,
    _check_text_cut_off,
    _check_small_font,
    _check_missing_labels,
    _check_low_contrast,
    _check_colorblind,
    _check_legend,
    _check_outside_limits,
    _check_empty_and_categories,
    _check_scales,
    _check_layout,
)
