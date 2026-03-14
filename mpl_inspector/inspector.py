from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from weakref import WeakKeyDictionary

import matplotlib.pyplot as plt
from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.backend_bases import Event, KeyEvent, MouseEvent
from matplotlib.figure import Figure
from matplotlib.legend import Legend

from .adapters import AdapterRegistry, ArtistMetadata, format_metadata, get_default_registry
from .containers import find_container, find_contour_set
from .highlight import HighlightHandle, HighlightStyle, create_highlight
from .notebook import show_in_notebook, warn_if_notebook_backend_is_static
from .panel import InspectorPanel
from .provenance import infer_call

_INSPECTORS: WeakKeyDictionary[Figure, FigureInspector] = WeakKeyDictionary()


class FigureInspector:
    """Attach inspection behavior to a Matplotlib figure."""

    def __init__(
        self,
        figure: Figure,
        *,
        registry: AdapterRegistry | None = None,
        show_panel: bool = True,
        print_on_select: bool = True,
        toggle_key: str = "i",
    ) -> None:
        self.figure = figure
        self.registry = registry or get_default_registry()
        self.show_panel = show_panel
        self.print_on_select = print_on_select
        self.toggle_key = toggle_key

        self.enabled = True
        self.selected_artist: Artist | None = None
        self.selected_hit: dict[str, Any] | None = None
        self.hovered_artist: Artist | None = None
        self.hovered_hit: dict[str, Any] | None = None

        # Overlap cycling state: all candidates under cursor, current index
        self._overlap_candidates: list[tuple[Artist, dict[str, Any]]] = []
        self._overlap_index: int = -1
        self._last_event_pos: tuple[float, float] | None = None

        # Keyboard traversal state
        self._traversal_axes: Axes | None = None
        self._traversal_list: list[Artist] = []
        self._traversal_index: int = -1

        self._panel = InspectorPanel(figure) if show_panel else None
        self._hover_highlight = HighlightHandle()
        self._selection_highlight = HighlightHandle()
        self._connections: dict[str, int] = {}
        self._connect_events()
        self._show_idle_message()

    def enable(self) -> FigureInspector:
        self.enabled = True
        self._show_idle_message()
        self.figure.canvas.draw_idle()
        return self

    def disable(self) -> None:
        self.enabled = False
        self.hovered_artist = None
        self.hovered_hit = None
        self.selected_artist = None
        self.selected_hit = None
        self._hover_highlight.remove()
        self._selection_highlight.remove()
        if self._panel is not None:
            self._panel.show_disabled()
        self.figure.canvas.draw_idle()

    def disconnect(self) -> None:
        for connection_id in self._connections.values():
            self.figure.canvas.mpl_disconnect(connection_id)
        self._connections.clear()
        self._hover_highlight.remove()
        self._selection_highlight.remove()
        if self._panel is not None:
            self._panel.remove_all()

    def _ipython_display_(self) -> None:
        """Display the attached figure instead of the inspector repr in notebooks."""
        _display_figure(self.figure)

    def dump_tree(
        self,
        axes: Axes | None = None,
        *,
        filter_type: type | None = None,
        filter_label: str | None = None,
        include_hidden: bool = True,
    ) -> str:
        """Print the figure/axes/artist tree.

        Parameters
        ----------
        axes : Axes or None
            Restrict to a single axes. ``None`` means all axes.
        filter_type : type or None
            Only show artists that are instances of this type.
        filter_label : str or None
            Only show artists whose label contains this substring
            (case-insensitive).
        include_hidden : bool
            If ``False``, skip artists where ``visible=False``.
        """
        lines = [f"Figure -> {self._display_name(self.figure)}"]
        axes_list = [axes] if axes is not None else list(self.figure.axes)

        for index, axis in enumerate(axes_list):
            artist_lines: list[str] = []
            for artist in self._iter_axes_artists(axis):
                if filter_type is not None and not isinstance(artist, filter_type):
                    continue
                if not include_hidden and not artist.get_visible():
                    continue
                if filter_label is not None:
                    label = getattr(artist, "get_label", lambda: "")()
                    if filter_label.lower() not in (label or "").lower():
                        continue
                vis = "" if artist.get_visible() else " [hidden]"
                call = infer_call(artist)
                hint = f"  <- {call}" if call else ""
                artist_lines.append(
                    f"    - {self._display_name(artist)}{vis}{hint}"
                )
            if artist_lines or filter_type is None:
                lines.append(f"  Axes[{index}] -> {self._display_name(axis)}")
                lines.extend(artist_lines)

        tree = "\n".join(lines)
        print(tree)
        return tree

    def describe_artist(
        self,
        artist: Artist,
        *,
        hit: dict[str, Any] | None = None,
    ) -> ArtistMetadata:
        return self.registry.adapter_for(artist).describe(
            artist,
            hit=hit,
            renderer=self._renderer(),
        )

    def diagnose_visibility(self, artist: Artist) -> list[str]:
        """Return a list of reasons why *artist* may not be visible.

        If the returned list is empty, no obvious issues were found.
        """
        issues: list[str] = []

        if not artist.get_visible():
            issues.append("visible=False — artist is explicitly hidden")

        alpha = artist.get_alpha()
        if alpha is not None and alpha <= 0:
            issues.append(f"alpha={alpha} — fully transparent")

        axes = getattr(artist, "axes", None)
        if axes is not None and isinstance(axes, Axes):
            if not axes.get_visible():
                issues.append("parent Axes is not visible")
            if axes.figure is not None and not axes.figure.get_visible():
                issues.append("parent Figure is not visible")

            # Check if artist bbox is outside axes limits
            renderer = self._renderer()
            if renderer is not None:
                try:
                    bbox = artist.get_window_extent(renderer=renderer)
                    axes_bbox = axes.get_window_extent(renderer=renderer)
                    if bbox is not None and axes_bbox is not None:
                        if not bbox.overlaps(axes_bbox) and artist.get_clip_on():
                            issues.append(
                                "bounding box is outside axes viewport "
                                "and clip_on=True — artist is clipped away"
                            )
                except Exception:
                    pass

        # Check for zero-size data in common types
        from matplotlib.lines import Line2D
        from matplotlib.collections import Collection
        import numpy as np

        if isinstance(artist, Line2D):
            xdata = artist.get_xdata(orig=False)
            if len(xdata) == 0:
                issues.append("line has no data points")
        elif isinstance(artist, Collection):
            paths = artist.get_paths()
            offsets = artist.get_offsets()
            if len(paths) == 0 and len(offsets) == 0:
                issues.append("collection has no paths and no offsets")

        zorder = artist.get_zorder()
        if zorder < 0:
            issues.append(f"zorder={zorder} — may be hidden behind axes background")

        return issues

    def _dump_selected(self) -> None:
        """Dump the selected artist's metadata as JSON to console and clipboard."""
        if self.selected_artist is None:
            print("[inspector] No artist selected. Click an artist first.")
            return

        metadata = self.describe_artist(self.selected_artist, hit=self.selected_hit)
        container = find_container(self.selected_artist)
        d = metadata.to_dict()
        if container is not None:
            d.setdefault("relationships", {})["container"] = (
                f"{type(container).__name__} ({len(container)})"
            )
        call_hint = infer_call(self.selected_artist)
        if call_hint is not None:
            d.setdefault("relationships", {})["likely_call"] = call_hint

        text = json.dumps(d, indent=2, default=str)
        print(text)

        # Try to copy to clipboard via pyperclip (optional)
        try:
            import pyperclip  # type: ignore[import-untyped]
            pyperclip.copy(text)
            print("[inspector] Copied to clipboard.")
        except ImportError:
            print("[inspector] Install pyperclip to enable clipboard copy.")

    def _connect_events(self) -> None:
        canvas = self.figure.canvas
        self._connections = {
            "motion": canvas.mpl_connect("motion_notify_event", self._on_motion),
            "click": canvas.mpl_connect("button_press_event", self._on_button_press),
            "key": canvas.mpl_connect("key_press_event", self._on_key_press),
            "close": canvas.mpl_connect("close_event", self._on_close),
        }

    def _on_motion(self, event: MouseEvent) -> None:
        if not self.enabled:
            return

        artist, hit, _ = self._artist_at_event(event)
        if artist is self.selected_artist:
            artist = None
            hit = None

        # Update status bar on every move
        if self._panel is not None:
            self._panel.update_status(
                axes=event.inaxes,
                xdata=event.xdata,
                ydata=event.ydata,
                hovered=artist,
            )

        if artist is self.hovered_artist and self._same_hit(hit, self.hovered_hit):
            return

        self.hovered_artist = artist
        self.hovered_hit = hit
        self._refresh_hover_highlight()
        if self.selected_artist is None:
            self._show_idle_message()
        self.figure.canvas.draw_idle()

    def _on_button_press(self, event: MouseEvent) -> None:
        if event.button != 1:
            return
        if not self.enabled:
            return

        artist, hit, candidates = self._artist_at_event(event)
        self._overlap_candidates = candidates
        self._overlap_index = 0 if candidates else -1
        self._last_event_pos = (event.x, event.y) if event.x is not None else None
        self._select_artist(artist, hit)

    def _on_key_press(self, event: KeyEvent) -> None:
        if event.key == self.toggle_key:
            if self.enabled:
                self.disable()
            else:
                self.enable()
            return

        if not self.enabled:
            return

        if event.key == "escape":
            self._select_artist(None, None)
            self._overlap_candidates.clear()
            self._overlap_index = -1
            self._traversal_list.clear()
            self._traversal_index = -1
            self._traversal_axes = None
            return

        if event.key == "tab":
            self._cycle_overlap(forward=True)
            return

        if event.key == "shift+tab":
            self._cycle_overlap(forward=False)
            return

        if event.key in ("up", "down"):
            self._traverse_artists(
                forward=(event.key == "down"),
                event=event,
            )
            return

        if event.key == "t":
            axes = self._active_axes_for_tree(event)
            self.dump_tree(axes=axes)

        if event.key == "d":
            self._dump_selected()

        if event.key == "a":
            self._list_axes_artists(event)

        if event.key == "?":
            self._diagnose_selected()

    def _on_close(self, event: Event) -> None:
        self.disconnect()
        _INSPECTORS.pop(self.figure, None)

    def _active_axes_for_tree(self, event: KeyEvent) -> Axes | None:
        if self.selected_artist is not None:
            return getattr(self.selected_artist, "axes", None)
        if self.hovered_artist is not None:
            return getattr(self.hovered_artist, "axes", None)
        return getattr(event, "inaxes", None)

    def _select_artist(
        self,
        artist: Artist | None,
        hit: dict[str, Any] | None,
    ) -> None:
        self.selected_artist = artist
        self.selected_hit = hit
        self._refresh_selection_highlight()

        if artist is None:
            self._show_idle_message()
            self.figure.canvas.draw_idle()
            return

        metadata = self.describe_artist(artist, hit=hit)

        # Add container provenance if applicable
        container = find_container(artist)
        if container is not None:
            metadata.relationships["container"] = (
                f"{type(container).__name__} ({len(container)})"
            )

        # Add contour set info
        cs = find_contour_set(artist)
        if cs is not None:
            n_levels = len(cs.levels) if hasattr(cs, "levels") else "?"
            metadata.relationships["contour_set"] = f"ContourSet ({n_levels} levels)"

        # Add provenance inference
        call_hint = infer_call(artist)
        if call_hint is not None:
            metadata.relationships["likely_call"] = call_hint

        # Add overlap cycling hint
        if len(self._overlap_candidates) > 1:
            metadata.relationships["overlapping"] = (
                f"{self._overlap_index + 1}/{len(self._overlap_candidates)} "
                "(Tab/Shift+Tab to cycle)"
            )

        if self._panel is not None:
            self._panel.show_metadata(metadata, artist=artist)
        if self.print_on_select:
            print("\n" + format_metadata(metadata) + "\n")
        self.figure.canvas.draw_idle()

    def _show_idle_message(self) -> None:
        if self._panel is None:
            return

        if not self.enabled:
            self._panel.show_disabled()
            return

        if self.selected_artist is not None:
            metadata = self.describe_artist(self.selected_artist, hit=self.selected_hit)
            self._panel.show_metadata(metadata, artist=self.selected_artist)
            return

        if self.hovered_artist is not None:
            metadata = self.describe_artist(self.hovered_artist, hit=self.hovered_hit)
            self._panel.show_metadata(metadata, artist=self.hovered_artist)
            return

        self._panel.show_message(
            "Inspector\n"
            "hover/click inspect\n"
            "tab cycle  d dump"
        )

    def _refresh_hover_highlight(self) -> None:
        self._hover_highlight.remove()
        if self.hovered_artist is None:
            return
        handle = create_highlight(
            self.hovered_artist,
            style=HighlightStyle(color="#22d3ee", alpha=0.95, linewidth=2.0),
            renderer=self._renderer(),
        )
        if handle is not None:
            self._hover_highlight = handle

    def _refresh_selection_highlight(self) -> None:
        self._selection_highlight.remove()
        if self.selected_artist is None:
            return
        handle = create_highlight(
            self.selected_artist,
            style=HighlightStyle(color="#f97316", alpha=1.0, linewidth=2.5),
            renderer=self._renderer(),
        )
        if handle is not None:
            self._selection_highlight = handle

    def _traverse_artists(self, *, forward: bool, event: KeyEvent) -> None:
        """Walk through all artists in the current axes with Up/Down."""
        # Determine which axes to traverse
        target_axes = self._active_axes_for_tree(event)
        if target_axes is None:
            target_axes = getattr(event, "inaxes", None)
        if target_axes is None and self.figure.axes:
            target_axes = self.figure.axes[0]
        if target_axes is None:
            return

        # Rebuild list if axes changed
        if target_axes is not self._traversal_axes:
            self._traversal_axes = target_axes
            self._traversal_list = [
                a for a in self._iter_axes_artists(target_axes)
                if a.get_visible() and not getattr(a, "_mpl_inspector_internal", False)
            ]
            self._traversal_index = -1

        if not self._traversal_list:
            return

        step = 1 if forward else -1
        self._traversal_index = (self._traversal_index + step) % len(self._traversal_list)
        artist = self._traversal_list[self._traversal_index]
        self._select_artist(artist, {})

    def _list_axes_artists(self, event: KeyEvent) -> None:
        """Print a numbered list of all artists in the current axes."""
        axes = self._active_axes_for_tree(event)
        if axes is None:
            axes = getattr(event, "inaxes", None)
        if axes is None:
            print("[inspector] No active axes.")
            return

        artists = list(self._iter_axes_artists(axes))
        if not artists:
            print("[inspector] No artists in this axes.")
            return

        lines = [f"Artists in {self._display_name(axes)} ({len(artists)} total):"]
        for i, artist in enumerate(artists):
            vis = "" if artist.get_visible() else " [hidden]"
            call = infer_call(artist) or ""
            if call:
                call = f"  <- {call}"
            lines.append(f"  {i:3d}. {self._display_name(artist)}{vis}{call}")
        print("\n".join(lines))

    def _diagnose_selected(self) -> None:
        """Run visibility diagnostics on the selected artist and print results."""
        if self.selected_artist is None:
            print("[inspector] No artist selected. Click one first, then press ?")
            return

        issues = self.diagnose_visibility(self.selected_artist)
        name = self._display_name(self.selected_artist)
        if not issues:
            print(f"[inspector] {name}: no visibility issues detected.")
        else:
            lines = [f"[inspector] {name}: {len(issues)} issue(s) found:"]
            for issue in issues:
                lines.append(f"  - {issue}")
            print("\n".join(lines))

    def _cycle_overlap(self, *, forward: bool = True) -> None:
        """Cycle through overlapping artists at the last click position."""
        if not self._overlap_candidates:
            return
        step = 1 if forward else -1
        self._overlap_index = (self._overlap_index + step) % len(self._overlap_candidates)
        artist, hit = self._overlap_candidates[self._overlap_index]
        self._select_artist(artist, hit)

    def _artist_at_event(
        self,
        event: MouseEvent,
    ) -> tuple[Artist | None, dict[str, Any] | None, list[tuple[Artist, dict[str, Any]]]]:
        """Find the best artist at *event* and return all candidates for cycling.

        Returns ``(top_artist, hit_info, all_candidates)`` where
        ``all_candidates`` is sorted topmost-first for Tab cycling.
        """
        raw: list[tuple[float, int, Artist, dict[str, Any]]] = []
        artist_pool = list(self._iter_candidate_artists(event.inaxes))

        for index, artist in enumerate(artist_pool):
            if not artist.get_visible() or getattr(artist, "_mpl_inspector_internal", False):
                continue
            try:
                contains, details = artist.contains(event)
            except Exception:
                continue
            if not contains:
                continue
            raw.append((artist.get_zorder(), index, artist, details or {}))

        if raw:
            raw.sort(key=lambda item: (item[0], item[1]))
            # Build candidate list topmost-first for cycling
            candidates = [(a, h) for _, _, a, h in reversed(raw)]
            artist, hit = candidates[0]
            return artist, hit, candidates

        if event.inaxes is not None:
            return event.inaxes, {}, [(event.inaxes, {})]

        try:
            if self.figure.contains(event)[0]:
                return self.figure, {}, [(self.figure, {})]
        except Exception:
            pass

        return None, None, []

    def _iter_candidate_artists(self, axes: Axes | None) -> Iterable[Artist]:
        if axes is None:
            yield from self.figure.texts
            return

        yield from self._iter_axes_artists(axes)
        yield axes
        yield from self.figure.texts

    def _iter_axes_artists(self, axes: Axes) -> Iterable[Artist]:
        seen: set[int] = set()

        def emit(artist: Artist | None) -> Iterable[Artist]:
            if artist is None:
                return ()
            if id(artist) in seen:
                return ()
            seen.add(id(artist))
            return (artist,)

        for title_text in (axes.title, axes.xaxis.label, axes.yaxis.label):
            yield from emit(title_text)
        for artist in axes.lines:
            yield from emit(artist)
        for artist in axes.collections:
            yield from emit(artist)
        for artist in axes.patches:
            if artist is axes.patch:
                continue
            yield from emit(artist)
        for artist in axes.images:
            yield from emit(artist)
        for artist in axes.texts:
            yield from emit(artist)
        for artist in axes.artists:
            yield from emit(artist)
        legend = axes.get_legend()
        if isinstance(legend, Legend):
            yield from emit(legend)

    def _display_name(self, artist: Artist) -> str:
        metadata = self.describe_artist(artist)
        return metadata.subtitle and f"{metadata.title} [{metadata.subtitle}]" or metadata.title

    def _renderer(self) -> Any | None:
        canvas = self.figure.canvas
        renderer_getter = getattr(canvas, "get_renderer", None)
        if renderer_getter is None:
            return None
        try:
            return renderer_getter()
        except Exception:
            canvas.draw()
            return renderer_getter()

    def _same_hit(
        self,
        left: dict[str, Any] | None,
        right: dict[str, Any] | None,
    ) -> bool:
        """Safely compare hit dictionaries that may contain numpy arrays."""
        if left is right:
            return True
        if left is None or right is None:
            return False
        if left.keys() != right.keys():
            return False
        return all(self._same_hit_value(left[key], right[key]) for key in left)

    def _same_hit_value(self, left: Any, right: Any) -> bool:
        if left is right:
            return True

        # Handle array-like values first (common in Matplotlib hit details).
        try:
            import numpy as np

            if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
                return bool(np.array_equal(np.asarray(left), np.asarray(right)))
        except Exception:
            pass

        if isinstance(left, dict) and isinstance(right, dict):
            if left.keys() != right.keys():
                return False
            return all(self._same_hit_value(left[k], right[k]) for k in left)

        if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
            if len(left) != len(right):
                return False
            return all(self._same_hit_value(a, b) for a, b in zip(left, right))

        try:
            result = left == right
        except Exception:
            return False

        if isinstance(result, bool):
            return result

        try:
            return bool(result)
        except Exception:
            return False


def inspect(
    fig: Figure | None = None,
    *,
    show_panel: bool = True,
    print_on_select: bool = True,
    toggle_key: str = "i",
    registry: AdapterRegistry | None = None,
    display: bool = False,
) -> FigureInspector:
    """Enable inspection mode for a figure and return its controller."""

    figure = fig or plt.gcf()
    inspector = _INSPECTORS.get(figure)
    if inspector is None:
        inspector = FigureInspector(
            figure,
            registry=registry,
            show_panel=show_panel,
            print_on_select=print_on_select,
            toggle_key=toggle_key,
        )
        _INSPECTORS[figure] = inspector
    else:
        inspector.enable()
    if display:
        _display_figure(figure)
    return inspector


def enable(fig: Figure | None = None, **kwargs: Any) -> FigureInspector:
    """Alias for :func:`inspect`."""

    return inspect(fig=fig, **kwargs)


def display(
    fig: Figure | None = None,
    **kwargs: Any,
) -> FigureInspector:
    """Attach the inspector and display the figure in the active environment."""

    figure = fig or plt.gcf()
    return inspect(fig=figure, display=True, **kwargs)


def show(
    fig: Figure | None = None,
    **kwargs: Any,
) -> FigureInspector:
    """Backward-compatible alias for :func:`display`."""

    return display(fig=fig, **kwargs)


def disable(fig: Figure | None = None) -> bool:
    """Disable inspection mode for the given figure."""

    figure = fig or plt.gcf()
    inspector = _INSPECTORS.get(figure)
    if inspector is None:
        return False
    inspector.disable()
    return True


def _display_figure(figure: Figure) -> None:
    if not show_in_notebook(figure):
        warn_if_notebook_backend_is_static(figure)
        plt.show()
