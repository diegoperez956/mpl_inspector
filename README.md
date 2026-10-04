# mpl_inspector

`mpl_inspector` is a developer utility package that makes Matplotlib figures inspectable in a DevTools-like way. It adds hover highlighting, click-to-select inspection, and a compact metadata panel so you can answer the question: "what object drew this thing?"

```python
import mpl_inspector
```

## Headless mode for AI agents

No GUI needed. Run a plotting script, get a PNG + JSON per figure and a list of
problems with suggested fixes; the exit code is non-zero when errors remain:

```bash
mpl-inspect plot.py            # or: python -m mpl_inspector plot.py
```

```python
data = mpl_inspector.snapshot(fig)  # figure > axes > artists as JSON-ready dict
issues = mpl_inspector.lint(fig)    # [{"code", "severity", "message", "fix", "location"}, ...]
```

Diagnostics cover overlapping/cut-off text and tick labels, missing labels and
titles, small fonts, low contrast, colorblind-unsafe colors and rainbow
colormaps, legends covering data, data outside the view, empty axes, too many
categories, inconsistent scales across subplots, and layout-engine failures.
See [AGENT.md](AGENT.md) for the schema, every diagnostic code, and the
plot → inspect → fix loop with a worked example.

## Capabilities

- Hover over supported artists and see a visual highlight.
- Click an artist to select it and inspect its metadata.
- **Tab / Shift+Tab** to cycle through overlapping artists under the cursor.
- **Up / Down arrows** to traverse all artists in the current axes without clicking.
- **Status bar** at the bottom showing cursor coords, active axes, and hovered artist.
- **Minimal summary chip** anchored inside the active axes instead of a large fixed side panel.
- **Notebook-friendly display API** via `mpl_inspector.display(fig)`.
- **Responsive widget sizing** for `ipympl` canvases in notebooks.
- **Notebook fit helper** via `mpl_inspector.fit_figure_to_cell(fig)` for oversized figures.
- **Provenance inference** — shows the likely plotting call (e.g. `ax.bar()`, `ax.scatter()`) that created each artist.
- **Breadcrumb paths** (Figure > Axes > Artist) in metadata output.
- **Container provenance** — selected bar/errorbar/stem artists show their owning container.
- **Per-point scatter detail** — individual point coordinates shown for scatter selections.
- **JSON dump** — press `d` to dump selected metadata as JSON (copies to clipboard with `pyperclip`).
- **`metadata.to_dict()`** — export metadata as a plain dict (JSON-serializable).
- **Visibility diagnostics** — press `?` or call `inspector.diagnose_visibility(artist)` to find out why an artist isn't visible.
- **Artist listing** — press `a` to print a numbered list of all artists in the current axes with provenance hints.
- **Filtered tree dump** — `dump_tree()` supports `filter_type`, `filter_label`, and `include_hidden` parameters.
- Toggle the inspector on or off with `i`.
- Clear the current selection with `Esc`.
- Print a quick figure/axes artist tree with `t`.

Supported artist types:

- `Line2D`
- scatter / `PathCollection`
- `PolyCollection` / `fill_between`
- `QuadMesh` / `pcolormesh`
- bars and other `Patch` subclasses such as `Rectangle`
- `Text` / `Annotation`
- `Spine`
- `Axes` (with formatter, locator, aspect, autoscale info)
- `Legend`
- `AxesImage` from `imshow`
- generic figure fallback

Container types detected: `BarContainer`, `ErrorbarContainer`, `StemContainer`.

## Installation

For local development:

```bash
python -m pip install -e .
```

Install directly from GitHub once the repository is pushed:

```bash
python -m pip install "mpl_inspector @ git+https://github.com/diegoperez956/mpl_inspector.git"
```

After the first PyPI release, the intended install command is:

```bash
python -m pip install mpl-inspector
```

For tests:

```bash
python -m pip install -e .[dev]
pytest
```

## Quick start

Attach the inspector after building a plot and before `plt.show()`:

```python
import numpy as np
import matplotlib.pyplot as plt
import mpl_inspector

x = np.linspace(0, 10, 200)
fig, ax = plt.subplots()
ax.plot(x, np.sin(x), label="signal", linewidth=2)
ax.scatter(x[::20], np.sin(x[::20]), s=90, label="samples")
ax.legend()

mpl_inspector.inspect(fig)
plt.show()
```

For a one-call convenience path:

```python
mpl_inspector.display(fig)
```

Public API:

```python
inspector = mpl_inspector.inspect(fig=None)
inspector = mpl_inspector.enable(fig=None)
inspector = mpl_inspector.display(fig=None)
inspector = mpl_inspector.show(fig=None)
disabled = mpl_inspector.disable(fig=None)

# Programmatic access
metadata = inspector.describe_artist(some_artist)
metadata.to_dict()  # JSON-serializable dict

# Visibility debugging
issues = inspector.diagnose_visibility(some_artist)
# Returns e.g. ["visible=False — artist is explicitly hidden"]

# Provenance inference
call = mpl_inspector.infer_call(some_rectangle)
# Returns e.g. "ax.bar() / ax.barh()"

# Container provenance
container = mpl_inspector.find_container(some_rectangle)
# Returns e.g. BarContainer or None

# Notebook widget cleanup
mpl_inspector.configure_widget_canvas(fig)
mpl_inspector.autosize_widget_canvas(fig)
mpl_inspector.fit_figure_to_cell(fig)

# Filtered tree dump
inspector.dump_tree(filter_type=Line2D, include_hidden=False)
inspector.dump_tree(filter_label="signal")
```

If `fig` is omitted, the current figure from `matplotlib.pyplot.gcf()` is used.

### Keyboard shortcuts

| Key | Action |
|---|---|
| `i` | Toggle inspector on/off |
| `Esc` | Clear selection and traversal |
| `Tab` | Cycle forward through overlapping artists |
| `Shift+Tab` | Cycle backward |
| `Up` / `Down` | Traverse all artists in current axes |
| `t` | Print artist tree to console |
| `d` | Dump selected metadata as JSON |
| `a` | List all artists in current axes |
| `?` | Diagnose visibility issues on selected artist |

## Running the demo

Use an interactive Matplotlib backend such as `TkAgg`, `QtAgg`, or `MacOSX`:

```bash
python examples/demo.py
```

If your environment defaults to a non-interactive backend like `Agg`, set one explicitly before running the demo:

```bash
MPLBACKEND=TkAgg python examples/demo.py
```

## Jupyter notebooks

For inline interactive inspection, use the Matplotlib widget backend:

```python
%matplotlib widget
import matplotlib.pyplot as plt
import mpl_inspector

fig, ax = plt.subplots()
ax.plot([0, 1], [0, 1], label="line")

mpl_inspector.display(fig)
```

`mpl_inspector.display(fig)` will:

- attach the inspector
- display `fig.canvas` directly when the widget backend is active
- hide notebook widget chrome for a more minimal presentation
- give widget canvases responsive sizing defaults
- shrink oversized figures to a more notebook-friendly starting size
- fall back to `plt.show()` outside widget-backed notebooks

If you prefer a single call that still reads like normal inspection setup:

```python
inspector = mpl_inspector.inspect(fig, display=True)
```

If the figure appears twice in a notebook, create it under `plt.ioff()` before displaying:

```python
with plt.ioff():
    fig, ax = plt.subplots()
```

If you want the same cleanup without displaying immediately:

```python
mpl_inspector.configure_widget_canvas(fig)
mpl_inspector.autosize_widget_canvas(fig)
mpl_inspector.fit_figure_to_cell(fig)
mpl_inspector.inspect(fig)
```

## How it works

The package is intentionally small, but organized to grow cleanly:

- `inspector.py` — figure-level state, event handling, selection, traversal, overlap cycling, visibility diagnostics, JSON dump.
- `adapters.py` — adapter registry and type-specific metadata extraction (13 adapters).
- `containers.py` — maps artists back to owning containers and ContourSets.
- `provenance.py` — heuristic inference of the plotting call that created each artist.
- `highlight.py` — temporary highlight overlays for hover/selection.
- `panel.py` — minimal axes-anchored summary chip plus status bar.
- `notebook.py` — widget-backend notebook display helpers.

The main extension point is the adapter registry. To add support for a new artist type:

```python
from mpl_inspector import ArtistAdapter, AdapterRegistry

class MyAdapter(ArtistAdapter):
    artist_type = MyCustomArtist

    def describe(self, artist, *, hit=None, renderer=None):
        metadata = super().describe(artist, hit=hit, renderer=renderer)
        metadata.properties["custom_field"] = artist.get_custom_value()
        return metadata

registry = mpl_inspector.get_default_registry()
registry.register(MyAdapter)
inspector = mpl_inspector.inspect(fig, registry=registry)
```

## Optional dependencies

- `pyperclip` — enables clipboard copy when pressing `d` to dump metadata.

## Publishing

Release automation is prepared for GitHub Actions + PyPI Trusted Publishing. See [RELEASING.md](/Users/diego/Downloads/mpl_inspector/RELEASING.md) for the exact steps.

## Limitations

- Notebook interactivity is best with `ipympl` and `%matplotlib widget` / `%matplotlib ipympl`.
- Highlighting is best on interactive backends. Tests use `Agg`, which validates logic but not live interaction.
- Scatter highlighting outlines the whole collection; per-point highlighting is a future goal.
- Bounding-box highlights for text-like artists can become stale after resize until the next interaction.
- No dedicated docked window yet.

## Roadmap

### v0.4+
- Docked Qt/Tk inspector pane (optional dependency)
- Per-point scatter highlighting (highlight single point, not whole collection)
- ContourSet adapter (contour lines as collections are already supported)
- Multi-select or lasso selection
- Event/change logging
- Reproducible code generation from selected artist
