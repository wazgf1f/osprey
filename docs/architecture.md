# Architecture

Osprey is deliberately small: one loop, one task interface, one matcher, one
input layer. This document explains how the pieces fit and why they are built
the way they are.

## Data flow

```
+---------+     +-------------+     +----------+     +----------+
| desktop | --> | GdiGrabber  | --> |  Frame   | --> | matcher  |
+---------+     |  (BitBlt)   |     | BGRA+ori |     | (NCC)    |
                +-------------+     +----------+     +----+-----+
                                                          |
                                                     Detection
                                                          |
                                              +-----------v-----------+
                                              |      Task.step()      |
                                              |  locate / click / key |
                                              +-----------+-----------+
                                                          |
                                               +----------v----------+
                                               |  InputController    |
                                               |  SendInput + human  |
                                               +---------------------+
```

The engine drives this at a fixed rate. A task never captures or sleeps
directly unless it wants to; the context offers both.

## Coordinates

There are three spaces, and mixing them up is the most common source of
"it clicks 200 px off" bugs:

1. **Image space** - pixels inside a frame, origin at its top-left.
   `Detection.x/y` live here.
2. **Desktop space** - Win32 screen pixels, origin at the virtual desktop's
   top-left. Capture returns its region origin in `Frame.origin`.
3. **Normalised mouse space** - SendInput's 0..65535 range, computed from the
   virtual desktop metrics.

`ctx.point(det)` is the only conversion a task should need:
`det.center + frame.origin`.

Sub-frames keep the maths honest: `Frame.crop(x, y, w, h)` slices the
pixels and adds the offset to the origin, so detections inside a region still
map to the right desktop pixel.

## Capture

`GdiGrabber` creates a 32-bit DIB section once, selects it into a
memory DC, and BitBlts the screen into it on every grab. The DIB's pixel memory
is wrapped by `numpy.ctypeslib.as_array`, so no copy happens until
`Frame` takes one (needed because the next grab overwrites the buffer).

Why not GetDIBits? It requires the bitmap not to be selected into a DC and
costs an extra copy. A DIB section avoids both.

DPI: `enable_dpi_awareness()` calls
`SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`, falling back to
`shcore.SetProcessDpiAwareness` and then `SetProcessDPIAware`.
Without it, a scaled display reports logical resolution, GDI stretches the
image, and input coordinates drift from captured pixels.

Resolution changes are handled at runtime: every grab re-reads the desktop
rectangle and rebuilds the DIB section when it changed. A region that no longer
fits raises instead of capturing the wrong area. `full_desktop=True` captures
the whole virtual screen, which is the safe choice when a window may be dragged
between monitors; coordinates then include negative origins.

`monitors()` and `screen_scale()` expose the display layout for diagnostics.
Neither is used by the matcher - it only sees pixels.

## Resolution and scaling

A template is a block of pixels, so it has no inherent scale. Windows display
scaling changes how many pixels a control occupies: the same button is 1.5x
wider at 150%. Two consequences follow.

First, the engine itself must never hardcode a size. It does not: frames carry
their dimensions and origin, detections are frame-relative, and the input layer
normalises against the live virtual desktop.

Second, a template captured on one machine may not match another machine at a
different scaling. `scales` exists for that case: each entry resizes the
template and repeats the search, and results are merged. Capturing templates on
the target machine (`osprey crop`) avoids the problem entirely and is the
recommended workflow.

The pyramid is independent of this: it treats the image and template at a fixed
ratio, then refines at full resolution.

## Matching

### Score

For an image `I` and template `T`, at every valid offset:

```
              sum( (T - mean(T)) * (I_patch - mean(I_patch)) )
NCC = ---------------------------------------------------------
        sqrt( sum((T - mean(T))^2) * sum((I_patch - mean(I_patch))^2) )
```

The score is 1.0 for a pixel-perfect match, 0 for no correlation, -1 for an
inverted match. It is invariant to brightness and contrast changes, which is
why it works across theme changes and gamma differences.

### Fast computation

The numerator is a correlation, computed as a convolution with the flipped
template via FFT:

```
numerator = irfft2( rfft2(image) * rfft2(flip(template - mean)) )
```

The denominator needs per-window sums of `I` and `I^2`, which
are constant-time queries on two integral images. Both integral images are
built once per call, then sliced per template size.

Edge handling: zero-padding to `H + h - 1` and `W + w - 1` makes
the circular convolution linear; the valid region starts at `(h-1, w-1)`.

Accuracy: the implementation is verified against a brute-force, window-by-window
NCC over thousands of positions (`tests/test_match.py`, tolerance 1e-6).

### Pyramid

Above one megapixel, matching runs on a half-resolution image first (quarter
above eight megapixels). The coarse pass is a proposal generator only: its
peaks are **not** thresholded, because fine textures can fall to ~0.3 at half
resolution even at the true location. Each proposal is re-scored on the full
image inside a small window, and the real threshold is applied there.

That keeps accuracy identical to a full search (tested) while cutting the FFT
area by 4x. It costs a handful of tiny full-resolution correlations per frame.

### Multi-scale and NMS

`scales` resizes the template and repeats the search. Candidates from
all scales are merged with greedy non-maximum suppression on IoU, then sorted
by score. Duplicate scales are skipped, and scales whose template would not fit
are dropped.

## Input

`SendInput` is used directly, with explicit `argtypes` so 64-bit
pointers are not truncated. Three details matter:

- **Scan codes, not virtual keys.** Keyboard events use
  `KEYEVENTF_SCANCODE`, which is what DirectInput-era games read.
  Extended keys (arrows, right ctrl/alt) get `KEYEVENTF_EXTENDEDKEY`.
- **Absolute mouse coordinates** are normalised over the virtual desktop with
  `MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK`. Relative mode is
  available for engines that only honour deltas.
- **Structure layout** is asserted in tests (`INPUT` is 40 bytes on
  x64). A wrong layout sends garbage, so it is worth locking down.

Humanised movement uses a cubic Bezier with random lateral bow, ease-out timing
and jittered step delays. The final step snaps to the exact target so the click
lands precisely. Every action is recorded in `InputController.history`,
which is what dry-run tests assert against.

## Engine lifecycle

```
setup -> loop { check safety, grab, task.step, pace } -> teardown
```

- The first frame is grabbed before `setup`, so tasks can size
  themselves from `ctx.frame`.
- Pacing uses an absolute deadline per tick; a late tick resets the deadline
  instead of bursting to catch up.
- `finally` always releases held keys, calls `teardown` and
  closes the source if the engine owns it. Injected sources are owned by the
  caller (tests rely on this).
- Unexpected task exceptions are logged, counted in `Stats.errors` and
  re-raised after cleanup.

## Safety

`Safety._poll()` checks, in order: explicit stop request, stop file,
panic keys, runtime cap. It is called both from the loop (raising
`Aborted`) and from the input layer as a guard callback (returning
False), so a long click sequence cannot outlive an abort.

`GetAsyncKeyState` is used rather than a keyboard hook: no message loop,
no DLL, and it works while the engine thread is busy.

## Extension points

- **Task**: subclass `Task`; the engine only needs `step`.
- **Frame source**: implement `grab()` and `close()` and pass it
  to `Engine(source=...)`. A video player is a useful test double.
- **Matcher backend**: `match_template(backend=...)` already switches
  between numpy and OpenCV. A new backend needs a score map with the same shape
  semantics.
- **Vision extras**: OCR, colour checks or contour logic belong in a task that
  calls `ctx.gray` - the engine does not need to know.

## Testing strategy

- Brute-force reference for the correlator (the single most important test).
- Pyramid results must equal full-resolution results on the same scene.
- Struct sizes and key parsing for input.
- Fake frame source for the engine, so timing and teardown are tested without a
  desktop.
- Live capture tests are Windows-only and skipped elsewhere.
- `tools/selftest.py` is the manual end-to-end check: capture, cut a
  patch, find it again, report timing and error in pixels.
