# mpl_inspector for AI coding agents

Use this when you write or fix Matplotlib code. You cannot see the chart, so let
`mpl-inspect` look at it for you: it runs the script headlessly (Agg backend, no
GUI, no event loop), saves every figure as PNG + JSON, and lists concrete layout,
readability and data problems with a suggested fix for each.

## The loop

1. Write the plotting script.
2. Run `mpl-inspect script.py` (or `python -m mpl_inspector script.py`).
3. Exit code `0`: done. `1`: fix every `[error]` line (and warnings you agree with), go to 2.
   `2`: the script crashed or made no figure; read the traceback, fix, go to 2.
4. Optionally open the PNG (path printed on the last line) to eyeball the result.

Fix in this order: `script-error` > layout (`axes-*`, `layout-warning`,
`text-cut-off`, cross-subplot `text-overlap`) > everything else. One layout fix
(usually `layout="constrained"` or a bigger figure) often clears many diagnostics.

## CLI

```bash
mpl-inspect [-o OUT] [--fail-on error|warning|info|never] [--min-fontsize PT] [--json] script.py [-- script args]
```

| Exit | Meaning |
|---|---|
| 0 | no diagnostic at or above `--fail-on` (default `error`) |
| 1 | at least one such diagnostic |
| 2 | script raised, or produced no figures (figures made before a crash are still inspected) |

Outputs (default `OUT=mpl-inspect-out`): `OUT/<script>.json` and
`OUT/<script>-fig<N>.png`. Figures are captured from `plt.show()`, `plt.close()`,
`savefig()` and whatever is still open at the end. `matplotlib.use(...)` calls in
the script are ignored. stdout is one `[severity] figN target code: message` line
plus a `fix:` line per diagnostic; `--json` prints the whole report instead.

## Python API

```python
import mpl_inspector

data = mpl_inspector.snapshot(fig)   # JSON-ready dict describing the figure
issues = mpl_inspector.lint(fig)     # list of diagnostic dicts, most severe first
mpl_inspector.CODES                  # {code: (severity, description)}
```

Both draw the figure once on its own canvas; no `plt.show()` needed.
`mpl_inspector.inspect(fig)` is the separate interactive (hover/click) inspector.

## Report JSON

```text
{schema_version, script, argv, status: ok|script-error|no-figures, error: traceback|null,
 summary: {error, warning, info}, diagnostics: [script-level], report: path,
 figures: [{index, png, diagnostics: [...], snapshot: {...}}]}
```

Diagnostic:

```json
{"code": "tick-label-overlap", "severity": "error",
 "message": "8 of 8 x tick labels on ax0 overlap each other",
 "fix": "rotate: ax.tick_params(axis='x', labelrotation=45) + ...",
 "location": {"axes": 0, "target": "ax0.xticklabels", "bbox_display": [74.4, 14.4, 387.9, 28.8]}}
```

Snapshot (`schema_version` "1"):

```text
figure: schema_version, type, size_inches, dpi, size_px, facecolor, suptitle,
        layout_engine (null|"tight"|"constrained"|...), texts[], legends[], axes[]
axes:   id ("ax0"), index, visible, axis_on, is_colorbar, title, xlabel, ylabel,
        xaxis/yaxis {label, scale, lim, inverted, units (null|"category"|"date"), shared_with[]},
        aspect, facecolor, bbox_display, bbox_figure, legend {visible, entries[], bbox_display, bbox_data}|null,
        artists[]
artist: id ("ax0.3"), type, call (likely plotting call, e.g. "ax.bar() / ax.barh()"),
        container, label, visible, alpha, zorder, clip_on, bbox_display, bbox_data,
        n_points, data_extent {x: [min, max], y: [min, max]} (data coords) | null,
        colors {color | facecolor(s)/edgecolor(s) | cmap}
        + text, fontsize (Text)  + linewidth, linestyle, marker (Line2D)
```

Coordinates: `bbox_display` is `[x0, y0, x1, y1]` pixels at `dpi`, origin
**bottom-left** (PNG rows count from the top: `png_y = size_px[1] - y`). The PNG
is saved without `bbox_inches="tight"`, so pixels line up. `bbox_data` is the same
box in the axes' data coordinates. Colors are `#rrggbb`, or `#rrggbbaa` when
translucent. Non-finite numbers become `null`.

Targets: `ax0`, `ax0.3` (artist), `ax0.title`, `ax0.xlabel`, `ax0.ylabel`,
`ax0.xticklabels`, `ax0.legend`, `ax0.xaxis`, `fig.suptitle`, `fig.t0`.

## Diagnostic codes

| Code | Severity | Means |
|---|---|---|
| `tick-label-overlap` | error | tick labels on one axis collide |
| `text-overlap` | error | titles/labels/annotations collide, or text runs into another subplot |
| `text-cut-off` | error | text crosses the figure edge |
| `artist-outside-limits` | error | an artist is completely outside the view |
| `axes-overlap` | error | two axes overlap (twins and insets are fine) |
| `axes-collapsed` | error | an axes is under 5 px wide or tall |
| `script-error` | error | the script raised (CLI) |
| `no-figures` | error | the script made no figure (CLI) |
| `legend-covers-data` | warning | legend box sits on lines, points or bars |
| `missing-axis-label` | warning | axis with tick labels but no label (shared siblings count) |
| `small-font` | warning | text under `--min-fontsize` (default 8 pt) |
| `low-contrast` | warning | text < 3:1 or marks < 1.5:1 contrast against the background |
| `colorblind-unsafe` | warning | two same-style series look alike with protan/deutan/tritanopia |
| `rainbow-colormap` | warning | `jet`, `hsv`, `rainbow`, ... |
| `empty-axes` | warning | visible axes (or figure) with no data |
| `too-many-categories` | warning | > 10 legend entries, > 20 categories, > 8 pie wedges |
| `inconsistent-scales` | warning | same axis label, different scale or units |
| `layout-warning` | warning | tight/constrained layout gave up |
| `missing-title` | info | no axes title and no suptitle |
| `data-clipped` | info | some points outside the view or invalid for a log scale |
| `unshared-limits` | info | same axis label, different ranges, not shared |
| `runtime-warning` | info | any other warning raised while running/drawing |

## Worked example

`sales.py`:

```python
import matplotlib.pyplot as plt

regions = ["North America", "South America", "Western Europe", "Eastern Europe",
           "Middle East", "Sub-Saharan Africa", "South Asia", "East Asia"]
revenue = [42, 18, 35, 12, 9, 6, 22, 51]
growth = [3, 7, 2, 5, 9, 12, 8, 4]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8, 3.5))
ax1.bar(regions, revenue)
ax1.set_title("Revenue")
ax2.plot(regions, growth, color="#2ca02c", label="growth")
ax2.plot(regions, [5] * 8, color="#d62728", label="target")
ax2.legend(loc="center")
fig.savefig("sales.png")
```

```text
$ mpl-inspect sales.py
[error] fig0 ax0.xticklabels tick-label-overlap: 8 of 8 x tick labels on ax0 overlap each other
    fix: rotate: ax.tick_params(axis='x', labelrotation=45) + plt.setp(ax.get_xticklabels(), ha='right') ...; long category names read best on ax.barh
[error] fig0 ax1.xticklabels tick-label-overlap: 8 of 8 x tick labels on ax1 overlap each other
    fix: rotate: ax.tick_params(axis='x', labelrotation=45) + ...
[warning] fig0 ax0.xlabel missing-axis-label: ax0 has no x axis label
    fix: ax.set_xlabel('<quantity> (<unit>)')
  ... (same for ax0.ylabel, ax1.xlabel, ax1.ylabel)
[warning] fig0 ax1.0 colorblind-unsafe: ax1.0 'growth' (#2ca02c) and ax1.1 'target' (#d62728) look alike with deuteranopia (ΔE 7.3)
    fix: plt.style.use('tableau-colorblind10') or pick Okabe-Ito colors; also vary linestyle/marker so color is not the only cue
[warning] fig0 ax1.legend legend-covers-data: legend on ax1 covers data of ax1.0 'growth'
    fix: ax.legend(loc='best'), or move it outside: ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1), borderaxespad=0) with fig.set_layout_engine('constrained') ...
[info] fig0 ax1.title missing-title: ax1 has no title and the figure has no suptitle
    fix: ax.set_title('<what the chart shows>') or fig.suptitle(...)
1 figure(s): 2 error, 6 warning, 1 info
report: mpl-inspect-out/sales.json
png: mpl-inspect-out/sales-fig0.png
$ echo $?
1
```

Apply the fixes:

```python
plt.style.use("tableau-colorblind10")
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
ax1.barh(regions, revenue)
ax1.set(title="Revenue by region", xlabel="Revenue (USD M)", ylabel="Region")
ax2.plot(regions, growth, marker="o", label="growth")
ax2.plot(regions, [5] * 8, linestyle="--", label="target")
ax2.tick_params(axis="x", labelrotation=45)
ax2.set(title="Growth vs target", xlabel="Region", ylabel="YoY growth (%)")
ax2.legend(loc="upper left", bbox_to_anchor=(1.02, 1), borderaxespad=0)
fig.savefig("sales.png")
```

```text
$ mpl-inspect sales.py
1 figure(s): 0 error, 0 warning, 0 info
report: mpl-inspect-out/sales.json
png: mpl-inspect-out/sales-fig0.png
$ echo $?
0
```

## Limits

Checks are geometric heuristics on the drawn figure. Scatter extents use marker
centers, contrast over images/meshes is skipped, and legend overlap ignores
filled areas. Treat `info` as advice. If a warning is a deliberate choice (for
example a zoomed view), leave it and say why.
