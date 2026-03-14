# Notebook / UI Issue Backlog

This file tracks the next high-leverage fixes for `mpl_inspector`, with a bias toward notebook ergonomics and minimal UI polish.

## Resolved In This Pass

- [x] Notebook figures can be displayed through a first-class package API instead of relying on the last expression in a cell.
- [x] `inspect(..., display=True)` now attaches and renders in one call.
- [x] Added `mpl_inspector.display(fig)` as the primary intuitive notebook-friendly call.
- [x] ipympl widget canvases now get responsive sizing defaults (`width=100%`, computed height, stretch layout, `resizable=True`).
- [x] Kept `show()` as a compatibility alias for existing examples.

## Open Issues

- [ ] Replace the current text-based summary chip with a true anchored widget/offsetbox implementation.
- [ ] Add a notebook event-debug mode that logs motion/click/key events into a small output area.
- [ ] Improve per-point scatter highlighting so only the selected point is outlined.
- [ ] Add explicit support and tests for VS Code notebook rendering quirks.
- [ ] Add a compact docked metadata pane for Qt/Tk backends.
- [ ] Make overlap cycling discoverable in the UI without relying on keyboard memory.
- [ ] Add a dedicated `inspector.selected_metadata()` convenience method.
- [ ] Add frontend capability detection and a clearer warning when widget MIME output is not supported by the notebook host.
