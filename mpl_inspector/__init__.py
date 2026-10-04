"""Developer-oriented inspection tools for Matplotlib figures."""

from .adapters import ArtistAdapter, ArtistMetadata, AdapterRegistry, get_default_registry
from .containers import find_container, find_contour_set
from .inspector import FigureInspector, disable, display, enable, inspect, show
from .lint import CODES, lint
from .notebook import autosize_widget_canvas, configure_widget_canvas, fit_figure_to_cell
from .provenance import infer_call
from .snapshot import SCHEMA_VERSION, snapshot

__all__ = [
    "AdapterRegistry",
    "CODES",
    "SCHEMA_VERSION",
    "ArtistAdapter",
    "ArtistMetadata",
    "FigureInspector",
    "autosize_widget_canvas",
    "disable",
    "display",
    "enable",
    "configure_widget_canvas",
    "fit_figure_to_cell",
    "find_container",
    "find_contour_set",
    "get_default_registry",
    "infer_call",
    "inspect",
    "lint",
    "show",
    "snapshot",
]

__version__ = "0.3.0"
