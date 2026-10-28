# Changelog

All notable changes to this project are documented here. The format follows
Keep a Changelog, and the project uses semantic versioning.

## [Unreleased]

### Fixed

- Dry runs no longer touch Win32 APIs on non-Windows platforms.
- `click(x, y, move=False)` now jumps to the coordinates instead of clicking
  wherever the cursor already is.
- `SequenceTask(assets_dir=...)` is honoured for relative templates.
- Plan parsing raises `ConfigError` (not `ValueError`) for bad numbers, and
  accepts numeric strings.
- Invalid `press` keys and abort keys are rejected when the plan/config loads.
- `osprey run` task modules can import sibling helper modules.
- The visual editor closes its capture grabber after taking a template.
- A string `abort_keys` value is no longer split into single characters.
- Task factory/constructor errors in `osprey run` surface as `ConfigError`.
- Key-press steps are counted in run statistics.
- Closing the editor mid-run no longer posts callbacks to a destroyed window.
- Long key holds, typing and cursor glides can now be interrupted by the panic key.
- Aborting a run now releases held keys and mouse buttons even though the safety
  guard is already tripped.
- Degenerate template scales (a flat 1x1 resize) are skipped instead of failing
  the whole search.
- Released keys keep their original name in the action history.

## [0.1.0] - 2026-10-28

### Added

- GDI DIB-section screen capture with region support and DPI awareness.
- Automatic buffer rebuild when the resolution or monitor layout changes.
- Full-desktop capture across monitors, plus `monitors()` and `screen_scale()`.
- `osprey crop` for capturing templates at the current display scaling.
- FFT normalised cross-correlation matcher with multi-scale search, coarse-to-fine
  pyramid, NMS and an optional OpenCV backend.
- SendInput keyboard and mouse control: scan codes, absolute and relative mouse
  modes, Bezier movement, Unicode typing and dry-run history.
- Engine loop with fixed FPS, duration cap, panic keys, stop file and runtime cap.
- Task API, state machine and per-tick context with ROI detection helpers.
- CLI: `doctor`, `grab`, `find`, `run`.
- Test suite including brute-force NCC validation and pyramid parity checks.
- Examples: live click demo and offline pipeline demo.
- Declarative plan.json sequences with waits, loops and per-step timeouts.
- Tkinter visual editor: drag-to-capture templates, reorder steps, dry/live run.
- Installer UI with terms of use (agreement required), custom install path and progress.

### Notes

- Windows 10/11 only for capture and input.
- Primary monitor capture; input covers the virtual desktop.
