# Changelog

All notable changes to this project are documented here. The format follows
Keep a Changelog, and the project uses semantic versioning.

## [0.1.1] - 2026-10-28

### Added

- Duplicate a selected step in the editor with "复制步骤" or Ctrl+D,
  including its template, waits, threshold, timeout and scales.

### Changed

- Redesigned the plan editor: dark header, consistent typography, two-row
  toolbar, striped steps table, dark log panel and a status indicator.
- The editor captures across all monitors and runs plans with `all_screens`,
  so templates on a secondary display can be captured and clicked.
- Monitors left of the primary are positioned with Win32 `SetWindowPos`, since
  Tk reads negative geometry offsets as distances from the right edge.
- Plan steps reject non-path template values at load time instead of coercing
  them to strings and failing later at runtime.
- `EngineConfig` and `Safety` validate `stop_file` (accepting `PathLike`)
  instead of raising `TypeError` on the first poll.
- Plans built with `pathlib.Path` templates now serialize with `os.fspath`,
  so saving no longer fails inside `json.dump`.
- `Plan.validate` reports `ConfigError` for a non-list `steps` value or a
  non-`Step` entry instead of raising `AttributeError`.
- Editing a step in the visual editor no longer drops its per-step `scales`.

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
- `EngineConfig` coerces numeric strings and rejects NaN/infinity instead of
  failing with `TypeError`.
- Plan numbers must be finite; NaN/infinity raise `ConfigError`.
- Saving a plan into another directory pins its relative templates to absolute
  paths instead of silently breaking them.
- Plan and config JSON files with a UTF-8 BOM (Notepad default) now load.
- Unreadable plan paths are reported as `ConfigError` instead of `OSError`.
- `wait_for` rejects non-positive intervals and negative timeouts.
- Config and input reject NaN/infinity instead of spinning forever.
- `wait_for` and `Context.sleep` reject non-finite timeouts and durations.
- `hold`, `press`, `write` and `move_to` validate their timing parameters
  before sending any input event.
- The editor sizes itself to the available screen instead of assuming 1320x880.
- Clicking stop before the engine's first tick is now remembered and honored.
- Log callbacks are ignored after the editor window closes.
- `Safety` rejects non-finite `max_runtime` values.
- Editing controls (capture, add, move, delete, open, save) are disabled while
  a run is active, so capture no longer hides the window mid-run.
- Failing to write a captured template now shows an error dialog instead of
  raising inside the Tk callback.
- The installer version now comes from `osprey.__version__` (or
  `OSPREY_VERSION`), including the uninstall registry entry.
- Captured template names include microseconds plus a numeric fallback, so two
  captures in the same clock tick no longer overwrite each other.
- The engine closes its owned frame source when the first grab fails.
- If screen capture cannot even be initialised, the editor restores itself and
  shows an error instead of staying hidden.
- The editor window is clamped to the screen, including 800x600 and 1024x600.
- `osprey run` auto-detection ignores Task subclasses that were merely imported,
  so one local task class is no longer reported as ambiguous.
- A task's `teardown()` now runs even when `setup()` fails halfway, so partial
  resources are released.

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
