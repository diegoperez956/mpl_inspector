from __future__ import annotations

from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from .adapters import ArtistMetadata, format_metadata


class InspectorPanel:
    """Small figure overlay that shows the current inspector state."""

    def __init__(self, figure: Figure) -> None:
        self.figure = figure
        self._anchor_axes: Axes | None = None
        self.text_artist = figure.text(
            0.02,
            0.98,
            "",
            transform=figure.transFigure,
            ha="left",
            va="top",
            family="monospace",
            fontsize=8.5,
            linespacing=1.15,
            color="#0f172a",
            zorder=100_000,
            bbox={
                "boxstyle": "round,pad=0.25,rounding_size=0.2",
                "facecolor": "#f8fafc",
                "edgecolor": "#cbd5e1",
                "alpha": 0.94,
            },
        )
        self.text_artist._mpl_inspector_internal = True
        self.text_artist.set_clip_on(False)

        # Status bar at the bottom of the figure
        self._status_artist = figure.text(
            0.01,
            0.005,
            "",
            transform=figure.transFigure,
            ha="left",
            va="bottom",
            family="monospace",
            fontsize=8,
            color="#0f172a",
            zorder=100_000,
            bbox={
                "boxstyle": "square,pad=0.25",
                "facecolor": "#f8fafc",
                "edgecolor": "#cbd5e1",
                "alpha": 0.9,
            },
        )
        self._status_artist._mpl_inspector_internal = True
        self._status_artist.set_visible(False)

        self.show_message(
            "Inspector\n"
            "hover/click inspect\n"
            "tab cycle  d dump"
        )

    def show_message(self, message: str, *, artist: Artist | None = None) -> None:
        self._place_panel(artist=artist)
        self.text_artist.set_text(message)
        self.text_artist.set_visible(True)

    def show_metadata(
        self,
        metadata: ArtistMetadata,
        *,
        artist: Artist | None = None,
    ) -> None:
        self.show_message(_format_compact_metadata(metadata), artist=artist)

    def hide(self) -> None:
        self.text_artist.set_visible(False)

    def show_disabled(self) -> None:
        self.show_message("Inspector\nDisabled\npress i to re-enable")
        self._status_artist.set_visible(False)

    def update_status(
        self,
        *,
        axes: Axes | None = None,
        xdata: float | None = None,
        ydata: float | None = None,
        hovered: Artist | None = None,
    ) -> None:
        """Update the status bar with cursor info."""
        parts: list[str] = []

        if axes is not None:
            title = axes.get_title()
            if title:
                parts.append(f"Axes({title!r})")
            else:
                try:
                    idx = list(axes.figure.axes).index(axes)
                except ValueError:
                    idx = "?"
                parts.append(f"Axes[{idx}]")

        if xdata is not None and ydata is not None:
            parts.append(f"x={xdata:.4g}  y={ydata:.4g}")

        if hovered is not None:
            name = type(hovered).__name__
            label = getattr(hovered, "get_label", lambda: "")()
            if label and not label.startswith("_"):
                name += f"({label!r})"
            parts.append(name)

        if parts:
            self._status_artist.set_text("  |  ".join(parts))
            self._status_artist.set_visible(True)
        else:
            self._status_artist.set_visible(False)

    def remove_all(self) -> None:
        """Remove all panel artists from the figure."""
        for artist in (self.text_artist, self._status_artist):
            try:
                artist.remove()
            except ValueError:
                pass

    def _place_panel(self, *, artist: Artist | None = None) -> None:
        axes = getattr(artist, "axes", None)
        if isinstance(artist, Axes):
            axes = artist

        if isinstance(axes, Axes):
            self._anchor_axes = axes
            self.text_artist.set_transform(axes.transAxes)
            self.text_artist.set_position((0.02, 0.98))
        else:
            self._anchor_axes = None
            self.text_artist.set_transform(self.figure.transFigure)
            self.text_artist.set_position((0.02, 0.98))


def _format_compact_metadata(metadata: ArtistMetadata) -> str:
    """Use a short, anchored summary in-figure and keep full metadata for console dumps."""

    lines: list[str] = [metadata.title]
    if metadata.subtitle:
        lines[0] += f"  {metadata.subtitle}"

    likely_call = metadata.relationships.get("likely_call")
    container = metadata.relationships.get("container")
    overlap = metadata.relationships.get("overlapping")

    if likely_call:
        lines.append(str(likely_call))
    elif metadata.breadcrumb:
        lines.append(metadata.breadcrumb)

    if container:
        lines.append(str(container))

    if overlap:
        lines.append(str(overlap))

    summary_bits: list[str] = []
    for key in ("visible", "alpha", "zorder", "color", "linewidth", "marker", "markersize"):
        value = metadata.properties.get(key)
        if value not in ("", None, []):
            summary_bits.append(f"{key}={value}")
        if len(summary_bits) == 3:
            break
    if summary_bits:
        lines.append("  ".join(summary_bits))

    if not likely_call and not summary_bits:
        # Fall back to the original verbose representation for sparse metadata.
        return format_metadata(metadata)

    return "\n".join(lines)
