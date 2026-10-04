# mpl_inspector for AI coding agents

Use this when you write or fix Matplotlib code. You cannot see the chart, so let
`mpl-inspect` look at it for you: it runs the script headlessly (Agg backend, no
GUI, no event loop), saves every figure as PNG + JSON, and lists concrete layout,
readability and data problems with a suggested fix for each. When re-running is
slow or the figure lives in a notebook, attach to the live process with `mpl-axi`
instead (see [Live sessions](#live-sessions-mpl-axi)).

## The loop

1. Write the plotting script.
2. Run `mpl-inspect script.py` (or `python -m mpl_inspector script.py`).
3. Exit code `0`: done. `1`: fix every `error` row (and warnings you agree with), go to 2.
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
the script are ignored. stdout is compact TOON (`key: value`, `name[N]{cols}:`
tables, a closing `help[N]:` list of next commands); `--json` prints the whole
report instead.

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
status: ok
figures: 1
summary:
  error: 2
  warning: 6
  info: 1
diagnostics[9]{figure,severity,code,target,message,fix}:
  fig0,error,tick-label-overlap,ax0.xticklabels,8 of 8 x tick labels on ax0 overlap each other,"rotate: ax.tick_params(axis='x', labelrotation=45) + ..."
  fig0,error,tick-label-overlap,ax1.xticklabels,8 of 8 x tick labels on ax1 overlap each other,"rotate: ax.tick_params(axis='x', labelrotation=45) + ..."
  fig0,warning,missing-axis-label,ax0.xlabel,ax0 has no x axis label,ax.set_xlabel('<quantity> (<unit>)')
  ... (same for ax0.ylabel, ax1.xlabel, ax1.ylabel)
  fig0,warning,colorblind-unsafe,ax1.0,ax1.0 'growth' (#2ca02c) and ax1.1 'target' (#d62728) look alike with deuteranopia (ΔE 7.3),plt.style.use('tableau-colorblind10') or pick Okabe-Ito colors; also vary linestyle/marker so color is not the only cue
  fig0,warning,legend-covers-data,ax1.legend,legend on ax1 covers data of ax1.0 'growth',"ax.legend(loc='best'), or move it outside: ..."
  fig0,info,missing-title,ax1.title,ax1 has no title and the figure has no suptitle,ax.set_title('<what the chart shows>') or fig.suptitle(...)
report: mpl-inspect-out/sales.json
png[1]: mpl-inspect-out/sales-fig0.png
help[2]:
  "Apply the fixes, then run `mpl-inspect sales.py` again"
  Run `mpl-axi launch sales.py` to try fixes live without rerunning
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
status: ok
figures: 1
summary:
  error: 0
  warning: 0
  info: 0
report: mpl-inspect-out/sales.json
png[1]: mpl-inspect-out/sales-fig0.png
help[1]:
  Open the png to eyeball the result
$ echo $?
0
```

## Live sessions (mpl-axi)

Like Chrome DevTools Protocol, but for Matplotlib: a running Python process or
notebook exposes its figures over a local JSON-RPC protocol, and `mpl-axi`
attaches to it so you can inspect, change and re-render figures without
rerunning the script.

Start a session (opt-in; nothing listens otherwise):

```bash
mpl-axi launch plot.py            # runs plot.py headlessly, keeps its figures alive
```

```python
import mpl_inspector
mpl_inspector.serve()             # in your own process or notebook; pyplot figures are visible
mpl_inspector.serve(fig)          # also expose a figure made with Figure() directly
```

Then drive it:

```text
$ mpl-axi launch sales.py          # home view: session, figures, next steps
$ mpl-axi tree                     # refs for every element
nodes[20]{ref,parent,id,type,call,label,visible}:
  @f1,null,fig,Figure,null,"",true
  @x1,@f1,ax0,Axes,null,"",true
  @a1,@x1,ax0.title,Text,ax.set_title(),Revenue,true
  ...
$ mpl-axi lint                     # diagnostics, each with the ref to act on
diagnostics[9]{severity,code,ref,target,message,fix}:
  error,tick-label-overlap,@x1,ax0.xticklabels,8 of 8 x tick labels on ax0 overlap each other,...
$ mpl-axi invoke @x1 tick_params axis=x labelrotation=90
$ mpl-axi invoke @x2 tick_params axis=x labelrotation=90
$ mpl-axi invoke @f1 set_layout_engine constrained
$ mpl-axi set @a1 text="Revenue by region" fontsize=14
$ mpl-axi lint                     # summary: error: 0
$ mpl-axi screenshot @x1 ax.png    # PNG of one element (or the figure)
$ mpl-axi stop
```

Live fixes do not change the script. Once a fix works, write the same calls
into the script and confirm with `mpl-inspect`.

| Command | Does |
|---|---|
| `mpl-axi` | home view: attached session, figures, next steps |
| `sessions`, `attach <pid>` | list live sessions, choose one (or set `MPL_AXI_SESSION=<pid>`) |
| `launch <script> [-- args]` | run a script on Agg and serve its figures |
| `figures`, `tree [@f]` | list figures; list elements with refs |
| `get <ref>` | type, call, bbox and settable `props` |
| `set <ref> k=v ...` | `artist.set(k=v)` for each pair, then redraw; values parse as JSON, else text |
| `invoke <ref> <method> [arg ...] [k=v ...]` | call a public method, e.g. `tick_params`, `set_layout_engine`, `legend` |
| `screenshot [ref] [path.png]` | PNG of the figure or an element's box |
| `highlight <ref>`, `highlight --clear` | outline an element (shows in screenshots) |
| `lint [@f]` | diagnostics with refs |
| `snapshot [@f] [path.json]` | write the full snapshot JSON |
| `events [--count N] [--timeout S]` | wait for draw/resize/change notifications |
| `call <Domain.method> [json]` | raw protocol call |
| `stop` | shut the session down |

Every command prints TOON and ends with `help[N]` next steps; add `--json` for
the raw result. Errors print `error:`, `code:` and how to recover, with exit 1.

Refs: `@f<N>` figure, `@x<N>` axes, `@a<N>` any other element. They are assigned
in tree order and stay stable for the life of the object. Anywhere a ref is
accepted you can also pass a snapshot id (`ax0.3`, `ax0.title`). Lint rows carry
the ref of the element to fix; tick-label problems point at their axes.

### Protocol

JSON-RPC 2.0 over a WebSocket (text frames) at `ws://127.0.0.1:<port>/<token>`.
It binds to 127.0.0.1 only and refuses a wrong token. The session file
`$MPL_INSPECTOR_SESSIONS/<pid>.json` (default `~/.cache/mpl_inspector/sessions`,
mode 0600) holds `{pid, url, port, script, started}`. Request:
`{"jsonrpc": "2.0", "id": 1, "method": "Artist.set", "params": {"ref": "@a1", "props": {"fontsize": 14}}}`.
Errors: `{"error": {"code": -32000, "message": "...", "data": {"code": "NOT_FOUND"}}}`.

| Method | Params | Result |
|---|---|---|
| `Session.info` | | `{protocol, pid, url, python, matplotlib, backend, script, script_error, figures}` |
| `Session.methods` | | method names |
| `Session.shutdown` | | `{stopping}`; the server stops |
| `Figure.list` | | `[{ref, num, title, size_px, axes, artists}]` |
| `Figure.getTree` | `figure?` | `[{ref, parent, id, type, call, label, visible}]` |
| `Figure.snapshot` | `figure?` | the snapshot JSON (schema above) |
| `Figure.screenshot` | `figure?`, `ref?`, `path?`, `padding=8` | `{ref, width, height, bbox_display, path or data (base64 PNG)}` |
| `Artist.get` | `ref`, `figure?` | `{ref, type, call, bbox_display, props}` |
| `Artist.set` | `ref`, `props`, `figure?` | `{ref, applied, errors, props}` |
| `Artist.invoke` | `ref`, `method`, `args?`, `kwargs?`, `figure?` | `{ref, method, returned}` (public methods only) |
| `Artist.highlight` | `ref`, `color="#ff00ff"` | `{ref, highlights}` |
| `Artist.clearHighlights` | `figure?` | `{figure, cleared}` |
| `Lint.run` | `figure?`, `min_fontsize?` | diagnostics; `location.ref` added |
| `Events.subscribe` | `events?` (`draw`, `resize`, `change`) | `{events}`; then notifications `{"method": "Events.change", "params": {figure, ref, what}}` |
| `Events.unsubscribe` | | `{events: []}` |

`figure` defaults to the most recent figure. Error codes: `UNKNOWN_METHOD`,
`BAD_PARAMS`, `BAD_JSON`, `BAD_REF`, `BAD_METHOD`, `NOT_FOUND`, `NO_FIGURES`,
`NO_EXTENT`, `INTERNAL`. `Artist.set`/`invoke` call `fig.canvas.draw_idle()`
afterwards, so GUI and notebook (ipympl) canvases update on screen. Requests run
one at a time under a lock on the server thread; for GUI backends that require
main-thread drawing, prefer Agg or ipympl.

## Limits

Checks are geometric heuristics on the drawn figure. Scatter extents use marker
centers, contrast over images/meshes is skipped, and legend overlap ignores
filled areas. Treat `info` as advice. If a warning is a deliberate choice (for
example a zoomed view), leave it and say why.
