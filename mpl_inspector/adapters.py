from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable

import numpy as np
from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.collections import Collection, PathCollection, PolyCollection
from matplotlib.colors import to_hex
from matplotlib.figure import Figure
from matplotlib.image import AxesImage
from matplotlib.legend import Legend
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.spines import Spine
from matplotlib.text import Annotation, Text
from matplotlib.transforms import Bbox

# Conditional imports for artist types that may not exist in all mpl versions
try:
    from matplotlib.collections import QuadMesh
except ImportError:  # pragma: no cover
    QuadMesh = None  # type: ignore[misc,assignment]

try:
    from matplotlib.contour import ContourSet as _ContourSet
except ImportError:  # pragma: no cover
    _ContourSet = None  # type: ignore[misc,assignment]


@dataclass(slots=True)
class ArtistMetadata:
    """Structured information about an artist for panels and console output."""

    title: str
    subtitle: str = ""
    breadcrumb: str = ""
    properties: OrderedDict[str, Any] = field(default_factory=OrderedDict)
    data: OrderedDict[str, Any] = field(default_factory=OrderedDict)
    relationships: OrderedDict[str, Any] = field(default_factory=OrderedDict)

    def sections(self) -> list[tuple[str, OrderedDict[str, Any]]]:
        return [
            ("Properties", self.properties),
            ("Data", self.data),
            ("Relationships", self.relationships),
        ]

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for JSON serialization or copying."""
        result: dict[str, Any] = {"title": self.title}
        if self.subtitle:
            result["subtitle"] = self.subtitle
        if self.breadcrumb:
            result["breadcrumb"] = self.breadcrumb
        for heading, values in self.sections():
            cleaned = {k: _serialize_value(v) for k, v in values.items() if v not in ("", None, [])}
            if cleaned:
                result[heading.lower()] = cleaned
        return result


class ArtistAdapter:
    """Base adapter that exposes metadata for a Matplotlib artist."""

    artist_type = Artist

    def describe(
        self,
        artist: Artist,
        *,
        hit: dict[str, Any] | None = None,
        renderer: Any | None = None,
    ) -> ArtistMetadata:
        label = _normalize_label(artist.get_label())
        subtitle = label or _artist_path(artist)
        return ArtistMetadata(
            title=artist.__class__.__name__,
            subtitle=subtitle,
            breadcrumb=_breadcrumb(artist),
            properties=self._base_properties(artist, renderer=renderer),
            relationships=self._relationships(artist),
        )

    def _base_properties(
        self,
        artist: Artist,
        *,
        renderer: Any | None = None,
    ) -> OrderedDict[str, Any]:
        properties: OrderedDict[str, Any] = OrderedDict()
        properties["id"] = hex(id(artist))
        properties["label"] = _normalize_label(artist.get_label())
        properties["visible"] = artist.get_visible()
        properties["alpha"] = artist.get_alpha()
        properties["zorder"] = artist.get_zorder()
        properties["clip_on"] = artist.get_clip_on()
        properties["transform"] = artist.get_transform().__class__.__name__

        bbox = _safe_window_extent(artist, renderer=renderer)
        if bbox is not None:
            properties["bbox"] = _format_bbox(bbox)

        return properties

    def _relationships(self, artist: Artist) -> OrderedDict[str, Any]:
        relationships: OrderedDict[str, Any] = OrderedDict()
        figure = artist.figure
        axes = getattr(artist, "axes", None)

        if figure is not None and not isinstance(artist, Figure):
            relationships["figure"] = _figure_name(figure)

        if axes is not None and isinstance(axes, Axes):
            relationships["axes"] = _axes_name(axes)

        children = [child for child in artist.get_children() if not _is_internal(child)]
        if children:
            relationships["children"] = len(children)

        return relationships


class FigureAdapter(ArtistAdapter):
    artist_type = Figure

    def describe(
        self,
        artist: Figure,
        *,
        hit: dict[str, Any] | None = None,
        renderer: Any | None = None,
    ) -> ArtistMetadata:
        metadata = super().describe(artist, hit=hit, renderer=renderer)
        metadata.properties["size_inches"] = _format_pair(artist.get_size_inches())
        metadata.properties["dpi"] = artist.dpi
        metadata.properties["axes"] = len(artist.axes)
        metadata.properties["texts"] = len(
            [text for text in artist.texts if not _is_internal(text)]
        )
        return metadata


class AxesAdapter(ArtistAdapter):
    artist_type = Axes

    def describe(
        self,
        artist: Axes,
        *,
        hit: dict[str, Any] | None = None,
        renderer: Any | None = None,
    ) -> ArtistMetadata:
        metadata = super().describe(artist, hit=hit, renderer=renderer)
        metadata.subtitle = _axes_name(artist)
        metadata.properties["title"] = _clean_string(artist.get_title())
        metadata.properties["xlabel"] = _clean_string(artist.get_xlabel())
        metadata.properties["ylabel"] = _clean_string(artist.get_ylabel())
        metadata.properties["xlim"] = _format_pair(artist.get_xlim())
        metadata.properties["ylim"] = _format_pair(artist.get_ylim())
        metadata.properties["xscale"] = artist.get_xscale()
        metadata.properties["yscale"] = artist.get_yscale()
        metadata.properties["aspect"] = str(artist.get_aspect())
        metadata.properties["autoscale_on"] = artist.get_autoscale_on()

        # Formatter / locator info
        metadata.properties["xformatter"] = type(artist.xaxis.get_major_formatter()).__name__
        metadata.properties["yformatter"] = type(artist.yaxis.get_major_formatter()).__name__
        metadata.properties["xlocator"] = type(artist.xaxis.get_major_locator()).__name__
        metadata.properties["ylocator"] = type(artist.yaxis.get_major_locator()).__name__

        metadata.data["lines"] = len(artist.lines)
        metadata.data["collections"] = len(artist.collections)
        metadata.data["patches"] = len([p for p in artist.patches if p is not artist.patch])
        metadata.data["images"] = len(artist.images)
        metadata.data["texts"] = len(artist.texts)
        metadata.data["containers"] = len(artist.containers)
        return metadata


class Line2DAdapter(ArtistAdapter):
    artist_type = Line2D

    def describe(
        self,
        artist: Line2D,
        *,
        hit: dict[str, Any] | None = None,
        renderer: Any | None = None,
    ) -> ArtistMetadata:
        metadata = super().describe(artist, hit=hit, renderer=renderer)
        metadata.properties["color"] = _format_color(artist.get_color())
        metadata.properties["linewidth"] = artist.get_linewidth()
        metadata.properties["linestyle"] = artist.get_linestyle()
        metadata.properties["marker"] = artist.get_marker()
        metadata.properties["markersize"] = artist.get_markersize()
        metadata.properties["drawstyle"] = artist.get_drawstyle()

        xdata = np.asarray(artist.get_xdata(orig=False))
        ydata = np.asarray(artist.get_ydata(orig=False))
        metadata.data["points"] = len(xdata)
        metadata.data["x"] = _summarize_numeric(xdata)
        metadata.data["y"] = _summarize_numeric(ydata)

        hit_indices = _hit_indices(hit)
        if hit_indices:
            metadata.data["hit_indices"] = hit_indices

        return metadata


class CollectionAdapter(ArtistAdapter):
    artist_type = Collection

    def describe(
        self,
        artist: Collection,
        *,
        hit: dict[str, Any] | None = None,
        renderer: Any | None = None,
    ) -> ArtistMetadata:
        metadata = super().describe(artist, hit=hit, renderer=renderer)
        metadata.properties["facecolor"] = _format_colors(artist.get_facecolor())
        metadata.properties["edgecolor"] = _format_colors(artist.get_edgecolor())
        metadata.properties["linewidths"] = _summarize_numeric(np.asarray(artist.get_linewidths()))

        if hasattr(artist, "get_sizes"):
            metadata.properties["sizes"] = _summarize_numeric(np.asarray(artist.get_sizes()))

        cmap = getattr(artist, "get_cmap", lambda: None)()
        if cmap is not None:
            metadata.properties["cmap"] = cmap.name

        if isinstance(artist, PathCollection):
            offsets = np.asarray(artist.get_offsets())
            metadata.data["points"] = len(offsets)
            metadata.data["offsets"] = _summarize_points(offsets)
        else:
            metadata.data["paths"] = len(artist.get_paths())

        hit_indices = _hit_indices(hit)
        if hit_indices:
            metadata.data["hit_indices"] = hit_indices
            # Per-point detail for scatter plots
            if isinstance(artist, PathCollection):
                offsets = np.asarray(artist.get_offsets())
                for idx in hit_indices[:5]:
                    if 0 <= idx < len(offsets):
                        x, y = offsets[idx]
                        metadata.data[f"  [{idx}]"] = f"({_format_number(x)}, {_format_number(y)})"

        return metadata


class PatchAdapter(ArtistAdapter):
    artist_type = Patch

    def describe(
        self,
        artist: Patch,
        *,
        hit: dict[str, Any] | None = None,
        renderer: Any | None = None,
    ) -> ArtistMetadata:
        metadata = super().describe(artist, hit=hit, renderer=renderer)
        metadata.properties["facecolor"] = _format_color(artist.get_facecolor())
        metadata.properties["edgecolor"] = _format_color(artist.get_edgecolor())
        metadata.properties["linewidth"] = artist.get_linewidth()
        metadata.properties["linestyle"] = artist.get_linestyle()
        metadata.properties["fill"] = artist.get_fill()
        metadata.properties["hatch"] = artist.get_hatch()

        if isinstance(artist, Rectangle):
            metadata.data["x"] = _format_number(artist.get_x())
            metadata.data["y"] = _format_number(artist.get_y())
            metadata.data["width"] = _format_number(artist.get_width())
            metadata.data["height"] = _format_number(artist.get_height())

        return metadata


class TextAdapter(ArtistAdapter):
    artist_type = Text

    def describe(
        self,
        artist: Text,
        *,
        hit: dict[str, Any] | None = None,
        renderer: Any | None = None,
    ) -> ArtistMetadata:
        metadata = super().describe(artist, hit=hit, renderer=renderer)
        metadata.properties["text"] = _clean_string(artist.get_text())
        metadata.properties["color"] = _format_color(artist.get_color())
        metadata.properties["fontsize"] = artist.get_fontsize()
        metadata.properties["fontweight"] = artist.get_fontweight()
        metadata.properties["rotation"] = artist.get_rotation()
        metadata.data["position"] = _format_pair(artist.get_position())
        metadata.data["ha"] = artist.get_ha()
        metadata.data["va"] = artist.get_va()
        return metadata


class LegendAdapter(ArtistAdapter):
    artist_type = Legend

    def describe(
        self,
        artist: Legend,
        *,
        hit: dict[str, Any] | None = None,
        renderer: Any | None = None,
    ) -> ArtistMetadata:
        metadata = super().describe(artist, hit=hit, renderer=renderer)
        title = artist.get_title().get_text()
        labels = [text.get_text() for text in artist.get_texts()]
        metadata.properties["title"] = _clean_string(title)
        metadata.properties["entries"] = len(labels)
        metadata.data["labels"] = ", ".join(labels[:4]) + (" ..." if len(labels) > 4 else "")
        return metadata


class AxesImageAdapter(ArtistAdapter):
    artist_type = AxesImage

    def describe(
        self,
        artist: AxesImage,
        *,
        hit: dict[str, Any] | None = None,
        renderer: Any | None = None,
    ) -> ArtistMetadata:
        metadata = super().describe(artist, hit=hit, renderer=renderer)
        array = np.asarray(artist.get_array())
        metadata.properties["cmap"] = artist.get_cmap().name
        metadata.properties["interpolation"] = artist.get_interpolation()
        metadata.properties["origin"] = artist.origin
        metadata.data["shape"] = "x".join(str(dimension) for dimension in array.shape)
        metadata.data["extent"] = _format_quadruple(artist.get_extent())
        metadata.data["value_range"] = _summarize_numeric(array)
        return metadata


class AnnotationAdapter(TextAdapter):
    """Adapter for Annotation artists (Text subclass with arrow)."""

    artist_type = Annotation

    def describe(
        self,
        artist: Annotation,
        *,
        hit: dict[str, Any] | None = None,
        renderer: Any | None = None,
    ) -> ArtistMetadata:
        metadata = super().describe(artist, hit=hit, renderer=renderer)
        metadata.title = "Annotation"
        xy = artist.xy
        metadata.data["xy"] = _format_pair(xy)
        xycoords = artist.xycoords
        metadata.properties["xycoords"] = str(xycoords)

        if hasattr(artist, "xyann"):
            metadata.data["xytext"] = _format_pair(artist.xyann)

        arrow_props = artist.arrowprops
        if arrow_props:
            metadata.properties["arrowstyle"] = str(arrow_props.get("arrowstyle", "default"))

        return metadata


class SpineAdapter(ArtistAdapter):
    """Adapter for Spine artists (axes borders)."""

    artist_type = Spine

    def describe(
        self,
        artist: Spine,
        *,
        hit: dict[str, Any] | None = None,
        renderer: Any | None = None,
    ) -> ArtistMetadata:
        metadata = super().describe(artist, hit=hit, renderer=renderer)
        metadata.properties["spine_type"] = artist.spine_type
        metadata.properties["edgecolor"] = _format_color(artist.get_edgecolor())
        metadata.properties["linewidth"] = artist.get_linewidth()
        metadata.properties["linestyle"] = artist.get_linestyle()
        bounds = artist.get_bounds()
        if bounds is not None:
            metadata.data["bounds"] = str(bounds)
        position = artist.get_position()
        if position is not None:
            metadata.data["position"] = str(position)
        return metadata


class PolyCollectionAdapter(CollectionAdapter):
    """Adapter for PolyCollection (fill_between, etc.)."""

    artist_type = PolyCollection

    def describe(
        self,
        artist: PolyCollection,
        *,
        hit: dict[str, Any] | None = None,
        renderer: Any | None = None,
    ) -> ArtistMetadata:
        metadata = super().describe(artist, hit=hit, renderer=renderer)
        paths = artist.get_paths()
        metadata.data["paths"] = len(paths)
        total_vertices = sum(len(p.vertices) for p in paths)
        metadata.data["total_vertices"] = total_vertices
        return metadata


class QuadMeshAdapter(ArtistAdapter):
    """Adapter for QuadMesh (pcolormesh output)."""

    artist_type = type(None)  # placeholder; overridden in get_default_registry

    def describe(
        self,
        artist: Any,
        *,
        hit: dict[str, Any] | None = None,
        renderer: Any | None = None,
    ) -> ArtistMetadata:
        metadata = super().describe(artist, hit=hit, renderer=renderer)
        array = artist.get_array()
        if array is not None:
            arr = np.asarray(array)
            metadata.data["size"] = arr.size
            metadata.data["value_range"] = _summarize_numeric(arr)

        cmap = getattr(artist, "get_cmap", lambda: None)()
        if cmap is not None:
            metadata.properties["cmap"] = cmap.name

        metadata.properties["facecolor"] = _format_colors(artist.get_facecolor())
        metadata.properties["edgecolor"] = _format_colors(artist.get_edgecolor())
        return metadata


class AdapterRegistry:
    """Lookup table for artist adapters."""

    def __init__(self) -> None:
        self._instances: dict[type[Artist], ArtistAdapter] = {}

    def register(self, adapter_cls: type[ArtistAdapter]) -> None:
        self._instances[adapter_cls.artist_type] = adapter_cls()
        self._adapter_for_artist.cache_clear()

    def adapter_for(self, artist: Artist) -> ArtistAdapter:
        return self._adapter_for_artist(type(artist))

    @lru_cache(maxsize=128)
    def _adapter_for_artist(self, artist_type: type[Artist]) -> ArtistAdapter:
        for klass in artist_type.__mro__:
            adapter = self._instances.get(klass)
            if adapter is not None:
                return adapter
        return self._instances[Artist]


def get_default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    for adapter_cls in (
        ArtistAdapter,
        FigureAdapter,
        AxesAdapter,
        Line2DAdapter,
        CollectionAdapter,
        PolyCollectionAdapter,
        PatchAdapter,
        TextAdapter,
        AnnotationAdapter,
        LegendAdapter,
        AxesImageAdapter,
        SpineAdapter,
    ):
        registry.register(adapter_cls)

    # QuadMesh may not exist in older matplotlib versions
    if QuadMesh is not None:
        QuadMeshAdapter.artist_type = QuadMesh
        registry.register(QuadMeshAdapter)

    return registry


def format_metadata(metadata: ArtistMetadata) -> str:
    """Return a compact monospace-friendly representation."""

    lines = [metadata.title]
    if metadata.subtitle:
        lines.append(metadata.subtitle)
    if metadata.breadcrumb:
        lines.append(metadata.breadcrumb)

    for heading, values in metadata.sections():
        cleaned = [(key, value) for key, value in values.items() if value not in ("", None, [])]
        if not cleaned:
            continue
        lines.append("")
        lines.append(f"{heading}:")
        for key, value in cleaned:
            lines.append(f"  {key}: {_coerce_text(value)}")

    return "\n".join(lines)


def _safe_window_extent(artist: Artist, *, renderer: Any | None = None) -> Bbox | None:
    if renderer is None:
        return None
    try:
        bbox = artist.get_window_extent(renderer=renderer)
    except Exception:
        return None
    if bbox is None or not np.isfinite([bbox.x0, bbox.y0, bbox.x1, bbox.y1]).all():
        return None
    return bbox


def _hit_indices(hit: dict[str, Any] | None) -> list[int]:
    if not hit:
        return []
    indices = hit.get("ind")
    if indices is None:
        return []
    return [int(index) for index in np.atleast_1d(indices).tolist()]


def _artist_path(artist: Artist) -> str:
    axes = getattr(artist, "axes", None)
    if axes is not None and isinstance(axes, Axes) and artist is not axes:
        return f"{_figure_name(axes.figure)} -> {_axes_name(axes)}"
    figure = artist.figure
    if figure is not None and not isinstance(artist, Figure):
        return _figure_name(figure)
    return ""


def _axes_name(axes: Axes) -> str:
    title = _clean_string(axes.get_title())
    if title:
        return f"Axes(title={title!r})"
    try:
        index = list(axes.figure.axes).index(axes)
    except ValueError:
        index = "?"
    return f"Axes[{index}]"


def _figure_name(figure: Figure) -> str:
    return f"Figure({figure.get_figwidth():.1f}x{figure.get_figheight():.1f} in)"


def _format_bbox(bbox: Bbox) -> str:
    return (
        f"x={bbox.x0:.1f}, y={bbox.y0:.1f}, "
        f"w={bbox.width:.1f}, h={bbox.height:.1f} px"
    )


def _format_number(value: Any) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if np.isnan(number):
        return "nan"
    if abs(number) >= 1000 or (0 < abs(number) < 0.01):
        return f"{number:.3e}"
    return f"{number:.4g}"


def _format_pair(pair: Iterable[Any]) -> str:
    first, second = list(pair)[:2]
    return f"({_format_number(first)}, {_format_number(second)})"


def _format_quadruple(values: Iterable[Any]) -> str:
    left, right, bottom, top = list(values)[:4]
    return (
        f"left={_format_number(left)}, right={_format_number(right)}, "
        f"bottom={_format_number(bottom)}, top={_format_number(top)}"
    )


def _format_color(value: Any) -> str:
    if value is None or value == "none":
        return str(value)

    array = np.asarray(value)
    if array.ndim == 0:
        scalar = array.item()
        try:
            rgba = np.asarray(scalar, dtype=float)
        except (TypeError, ValueError):
            try:
                return to_hex(scalar, keep_alpha=True)
            except ValueError:
                return str(scalar)
        if rgba.shape == ():
            return str(scalar)

    try:
        rgba = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        try:
            return to_hex(value, keep_alpha=True)
        except ValueError:
            return str(value)

    if rgba.ndim == 1 and rgba.size in {3, 4}:
        return to_hex(rgba, keep_alpha=rgba.size == 4)

    if rgba.ndim >= 2 and rgba.shape[-1] in {3, 4}:
        return _format_colors(rgba)

    return str(value)


def _format_colors(colors: Any) -> str:
    array = np.asarray(colors)
    if array.size == 0:
        return ""
    if array.ndim == 1 and array.size in {3, 4}:
        return _format_color(array)

    preview = [
        to_hex(color, keep_alpha=color.shape[0] == 4)
        for color in np.asarray(array).reshape(-1, array.shape[-1])[:3]
    ]
    if len(array) > 3:
        preview.append("...")
    return ", ".join(preview)


def _summarize_numeric(values: np.ndarray) -> str:
    array = np.asarray(values)
    if array.size == 0:
        return "empty"

    flat = array.astype(float, copy=False).ravel()
    finite = flat[np.isfinite(flat)]
    if finite.size == 0:
        return f"shape={array.shape}, no finite values"

    preview_values = ", ".join(_format_number(value) for value in finite[:4])
    if finite.size > 4:
        preview_values += ", ..."

    return (
        f"shape={array.shape}, min={_format_number(finite.min())}, "
        f"max={_format_number(finite.max())}, sample=[{preview_values}]"
    )


def _summarize_points(points: np.ndarray) -> str:
    array = np.asarray(points)
    if array.size == 0:
        return "empty"

    if array.ndim != 2 or array.shape[1] < 2:
        return _summarize_numeric(array)

    x_values = array[:, 0].astype(float, copy=False)
    y_values = array[:, 1].astype(float, copy=False)
    return (
        f"n={len(array)}, "
        f"x=[{_format_number(np.nanmin(x_values))}, {_format_number(np.nanmax(x_values))}], "
        f"y=[{_format_number(np.nanmin(y_values))}, {_format_number(np.nanmax(y_values))}]"
    )


def _normalize_label(label: str | None) -> str:
    if not label or label.startswith("_"):
        return ""
    return label


def _clean_string(text: Any) -> str:
    if text is None:
        return ""
    return str(text).strip()


def _coerce_text(value: Any) -> str:
    text = str(value)
    if len(text) > 96:
        return text[:93] + "..."
    return text


def _is_internal(artist: Artist) -> bool:
    return bool(getattr(artist, "_mpl_inspector_internal", False))


def _breadcrumb(artist: Artist) -> str:
    """Build a Figure > Axes > Artist breadcrumb path."""
    parts: list[str] = []
    figure = artist.figure
    axes = getattr(artist, "axes", None)

    if figure is not None and not isinstance(artist, Figure):
        parts.append(_figure_name(figure))
    if axes is not None and isinstance(axes, Axes) and artist is not axes and not isinstance(artist, Axes):
        parts.append(_axes_name(axes))

    parts.append(artist.__class__.__name__)
    label = _normalize_label(artist.get_label())
    if label:
        parts[-1] += f"({label!r})"

    return " > ".join(parts)


def _serialize_value(value: Any) -> Any:
    """Coerce a metadata value to a JSON-safe type."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return str(value)
