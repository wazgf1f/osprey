# Osprey

[![CI](https://github.com/wazgf1f/osprey/actions/workflows/ci.yml/badge.svg)](https://github.com/wazgf1f/osprey/actions/workflows/ci.yml)

**Screen-vision automation for Windows.** Capture the screen, find things by template matching, and act through synthesised keyboard and mouse input.

Osprey is a small engine and library, not a framework you have to adopt wholesale: a readable Python core on top of NumPy, Pillow and the Win32 API.

Status: **0.1.1 alpha**, Windows 10/11, Python 3.9+.

## Why this exists

Most desktop automation addresses elements by name through UI Automation or the accessibility tree. That breaks for games, custom-drawn interfaces, remote desktops and anything painted onto a canvas. Osprey takes the other route: look at pixels, decide, act.

The architecture follows projects such as BetterGenshinImpact - capture, vision, decision, input - but stays focused on the engine rather than any single game.

## What it is, and what it is not

It is:

- a library and CLI for pixel-driven automation on Windows;
- a tested normalised-cross-correlation matcher with multi-scale search, a coarse-to-fine pyramid and an optional OpenCV fast path;
- a runner that is safe by default: dry runs, a panic key, a stop file and a runtime cap.

It is not:

- a memory reader, DLL injector or packet manipulator;
- an OCR or LLM agent - vision is template matching, and OCR belongs in your task;
- a tool for faking attendance, exams or any other academic credit. See **Responsible use**.

## Features

| Area | What you get |
|---|---|
| Capture | GDI DIB-section capture, ~40 ms for 2560x1600, region capture, per-monitor DPI awareness |
| Matching | FFT normalised cross-correlation, multi-scale, coarse-to-fine pyramid, NMS, OpenCV optional |
| Input | SendInput scan codes, absolute mouse over the virtual desktop, humanised Bezier movement, Unicode typing |
| Engine | Fixed-FPS loop, duration cap, panic key, stop file, graceful teardown, statistics |
| Safety | Dry run by default, F12 abort anywhere, keys released on exit |
| API | Tiny Task interface: setup / step / teardown, plus a small state machine |
| Editor | Visual step editor with drag-to-capture templates and dry/live run |

## Install

### Prebuilt (no Python required)

Run Osprey-0.1.1-Setup.exe. The installer shows the terms of use first: you
must tick "I have read and agree" to continue, and the install path is
customisable. It installs to %LOCALAPPDATA%\Programs\Osprey and adds Desktop
and Start Menu shortcuts. The terms state that this software must not be used
for attendance fraud, watch-time farming or any other academic dishonesty, and
that the user accepts all consequences of use.
For a portable copy, unzip Osprey-0.1.1-win64-portable.zip and run osprey.bat.

The executable is unsigned, so SmartScreen may warn about an unknown publisher:
choose **More info**, then **Run anyway**.

### From source

```bat
git clone https://github.com/wazgf1f/osprey.git
cd osprey
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

Optional, 5-10x faster matching on large screens:

```bat
pip install -e ".[opencv]"
```

Windows is required for screen capture and input. The vision and configuration modules import fine on other platforms, which is what CI uses.

Read [DISCLAIMER.md](DISCLAIMER.md) before use: this project is not for attendance
fraud or any other academic dishonesty.

## Quickstart

A step-by-step walkthrough in Chinese lives in [docs/quickstart.zh-CN.md](docs/quickstart.zh-CN.md).

Check that the environment can see the screen:

```bat
osprey doctor
```

```
osprey 0.1.1
python      : 3.12.14
platform    : Windows-11-10.0.26300-SP0 (AMD64)
numpy       : 2.3.5
pillow      : 12.3.0
opencv      : not installed (numpy backend will be used)
dpi aware   : True
dpi scale   : 1.500x
monitor 0   : 2560x1600 at (0, 0)  [primary]
screen      : 2560x1600 at origin (0, 0)
capture ms  : min 35.1  mean 41.4  max 47.3
brightness  : 151.1 (0 means a black or locked screen)
input       : ok (cursor moved and was restored)
status      : ready
```

If doctor reports **input BLOCKED**, the desktop refuses synthetic input - some
RDP sessions, sandboxes and secure desktops do. Capture and dry runs still work;
only live input is unavailable.

Save a screenshot and look for a template:

```bat
osprey grab shot.png
osprey find examples/assets/target.png --save marked.png
```

Cut a template straight out of the live screen - this is also the reliable way
to get a template that matches your display scaling:

```bat
osprey crop tasks\assets\accept.png --region 900,500,220,64
```

```
x=1476 y=814 w=64 h=64 score=1.0000 scale=1.000 desktop=(1476,814)
annotated frame saved to marked.png
```

Coordinates in the output are frame-relative; **desktop=(x, y)** is what you would pass to a click.

Or build a click sequence visually:

```bat
osprey gui
```

The editor captures templates by dragging a box, lets you reorder steps, set the wait
after each action, and runs the plan in dry or live mode. Save the result and run it
later with `osprey play plan.json`.

## Live demo

```bat
python tools/make_target.py
start examples\assets\target.png
python examples/click_demo.py
python examples/click_demo.py --live
```

The demo looks for the target card, reports its desktop position and clicks it once. Press **F12** to stop at any time.

## Writing a task

A task owns the decisions; the engine owns capture, timing, safety and teardown.

```python
# tasks/accept.py
from osprey.core.task import Task


class AcceptMatch(Task):
    name = "accept-match"

    def setup(self, ctx):
        self.template = "accept.png"   # resolved against assets_dir
        self.clicks = 0

    def step(self, ctx):
        button = ctx.locate(self.template, threshold=0.88)
        if button is None:
            return
        ctx.click(button)
        self.clicks += 1
        ctx.sleep(0.6)
        if self.clicks >= 3:
            ctx.safety.request_stop("done")
```

```json
{
  "threshold": 0.88,
  "scales": [1.0, 0.9, 1.1],
  "fps": 5,
  "assets_dir": "tasks/assets",
  "max_runtime": 300
}
```

```bat
osprey run tasks/accept.py --config tasks/config.json
osprey run tasks/accept.py --config tasks/config.json --live
```

A module with exactly one Task subclass is loaded automatically. With several,
expose TASK or create_task() so the CLI knows which one to run.

Everything a task touches hangs off the context:

| Member | Meaning |
|---|---|
| `ctx.frame` | Current BGRA frame with its desktop origin |
| `ctx.gray` | Luma view, computed once per frame |
| `ctx.locate(template, roi=..., scales=...)` | Best detection or `None` |
| `ctx.locate_all(...)` | Every detection above threshold |
| `ctx.wait_for(template, timeout=10)` | Block until something appears |
| `ctx.click(target)` | Click a detection or a frame-relative point |
| `ctx.move(target)` | Glide the cursor there |
| `ctx.sleep(seconds)` | Abortable sleep |
| `ctx.snapshot(path)` | Save the current frame for debugging |
| `ctx.safety` | Stop conditions and `request_stop()` |

## CLI reference

| Command | Purpose |
|---|---|
| `osprey doctor` | Check Python, dependencies, DPI awareness, capture latency and brightness |
| `osprey grab OUT.png [--region x,y,w,h] [--all-screens]` | Save a screenshot |
| `osprey crop OUT.png --region x,y,w,h` | Save a screen region as a template |
| `osprey gui [PLAN.json]` | Visual editor for click sequences |
| `osprey play PLAN.json [--live] [--loop N]` | Run a saved sequence |
| `osprey find TEMPLATE [--threshold T] [--scales 1.0,0.9] [--all-screens] [--save OUT.png]` | Locate a template on the live screen |
| `osprey run TASK.py [--config C] [--live] [--fps N] [--duration S]` | Run a task |

`--live` is the only switch that sends real input. Without it the run is a dry run: detections are computed, actions are logged, nothing is clicked.

## Configuration

| Key | Default | Meaning |
|---|---|---|
| `threshold` | 0.82 | Minimum NCC score, 0..1 |
| `scales` | `[1.0]` | Template scales to try |
| `nms_iou` | 0.3 | Overlap above which detections merge |
| `fps` | 8 | Loop rate |
| `dry_run` | true | Never send input |
| `abort_keys` | `["f12"]` | Panic keys, polled globally |
| `stop_file` | null | Run stops when this path exists |
| `max_runtime` | null | Hard cap in seconds |
| `speed` | 1.0 | Input speed multiplier |
| `move_mode` | absolute | `absolute` or `relative` mouse motion |
| `assets_dir` | . | Base directory for relative template paths |
| `all_screens` | false | Capture every monitor instead of the primary one |

Unknown keys are allowed, so a task can carry its own settings in the same file.

## Architecture

```
screen --GDI--> Frame(BGRA) --luma--> matcher --> Detection
                                         |
                                    task.step(ctx)
                                         |
                    ctx.click / key --> SendInput --> desktop
```

| Module | Responsibility |
|---|---|
| `osprey.capture` | GDI DIB-section grabber, `Frame` container |
| `osprey.vision` | NCC matcher, pyramid, NMS, image IO, overlays |
| `osprey.input` | SendInput keyboard and mouse, humanised paths, dry run |
| `osprey.core` | Engine loop, Task API, Context, Safety, configuration |
| `osprey.cli` | `doctor`, `grab`, `find`, `run` |

More detail, including the matching maths and coordinate model, is in [docs/architecture.md](docs/architecture.md).

## Resolution, DPI and monitors

Nothing in Osprey is tied to a resolution. Frame size, origin and click targets
are all derived from the desktop at run time.

- The process enables per-monitor DPI awareness, so pixels, `GetSystemMetrics`
  and cursor coordinates agree. Without it a 150% display reports 1707x1067 for
  a 2560x1600 panel and every click lands in the wrong place.
- The capture buffers are rebuilt automatically if the resolution or monitor
  layout changes mid-run. A region that no longer fits raises a clear error
  instead of silently capturing the wrong area.
- `osprey doctor` prints the DPI scale, every monitor and the virtual desktop.
- Capture covers the primary monitor by default; `--all-screens` captures every
  monitor as one frame. Input always addresses the whole virtual desktop, and
  `move_mode: "relative"` is there for engines that ignore absolute moves.

### Templates across display scaling

A template is pixels, so Windows scaling changes its apparent size: a button
captured at 100% appears 1.5x larger at 150%. Two ways to stay accurate:

1. **Capture on the target machine** with `osprey crop` (recommended). The
   template then matches at whatever scaling that machine uses.
2. **Search a scale range** when sharing templates between machines, for
   example `--scales 1.0,1.25,1.5` or the equivalent `scales` list in config.
   Each extra scale costs one more pass, so keep the list short.

## Performance

Measured on the development machine (Windows 11, 2560x1600, Python 3.12, NumPy 2.3.5, no OpenCV):

| Operation | Time |
|---|---|
| GDI capture | 35-47 ms |
| Match 56x56 template, pyramid enabled | 99-118 ms |
| Match 56x56 template, full resolution | ~381 ms |

The matcher runs in the frequency domain, so cost grows with frame area. Three knobs keep it practical:

1. **ROI**: `ctx.locate(template, roi=(x, y, w, h))` searches a rectangle instead of the whole screen.
2. **Pyramid**: enabled automatically above one megapixel; `downscale=2` or `4` forces it, `downscale=1` disables it.
3. **OpenCV**: `pip install -e ".[opencv]"` switches to `matchTemplate`, typically 5-10x faster.

## Safety

- **Dry run is the default.** Input is logged, not sent.
- **F12 aborts** anywhere, even while a task is sleeping, because it is polled with `GetAsyncKeyState`.
- **Stop file**: create the configured file and the run ends at the next check.
- **Runtime cap**: `max_runtime` bounds any run.
- **Release on exit**: held keys and buttons are released during teardown.
- Osprey does not require administrator rights.

## Limitations

- Template matching is sensitive to scale, rotation and transparency. Use `scales`; rotation and masks are not implemented yet.
- Windows only. Capture and input are Win32-specific.
- The secure desktop (UAC prompt, lock screen) captures as black.
- Some environments reject synthetic input entirely (certain RDP sessions,
  sandboxes, locked-down kiosks). Run `osprey doctor` first; it checks.
- Games using raw input or kernel anti-cheat may ignore synthetic input, or may detect it.
- No OCR, no text understanding, no scene graph.

## Responsible use

Use Osprey only on systems you own or are authorised to automate.

Automating a game or a service generally violates its terms of service, and anti-cheat systems are built to detect synthetic input. You can lose an account over it; that is your call, not the project's.

**Osprey is explicitly not intended for academic fraud.** Do not use it to fake attendance, watch-time, participation or assessment. Those rules exist for a reason, and a tool that automates them harms the people who follow them. Contributions whose purpose is to defeat attendance or exam checks will be rejected.

The authors accept no liability for misuse or for consequences of running this software.

## Development

```bat
python -m unittest discover -s tests -t . -v
python tools/selftest.py
```

The suite covers the matcher against a brute-force reference, the pyramid against full-resolution results, input encoding, configuration, the engine loop, safety guards and live capture (skipped outside Windows).

Layout:

```
src/osprey/        library
tests/             unittest suite
examples/          runnable examples and demo assets
tools/             maintenance scripts (selftest, target generator)
docs/              architecture notes
```

## Roadmap

- Template recorder (drag a box on screen, get a cropped template)
- Masked matching for transparent icons
- OCR hook with a pluggable engine
- Debug overlay showing detections live
- X11 backend for Linux
- OpenCV backend in CI with score parity tests

## License

MIT. See [LICENSE](LICENSE).

Osprey is not affiliated with miHoYo, HoYoverse or any game publisher.
