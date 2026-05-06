# Screenshot Builder

Batch-generate App Store / Play Store marketing screenshots locally from a YAML
recipe. Headless CLI, Python, high-quality image manipulation via Pillow.

For each *brand* you define, the tool takes a base image (e.g. a hand holding a
phone with a transparent display area), warps a plain screenshot into the four
corners of that display using a true perspective transform, and finally
composites optional stamps (logos) and text labels (with shadow) on top.

- **Author:** Thomas F Abrahamsson, Alvega & Co AB · `Thomas@alvega.company`
- **License:** © Thomas F Abrahamsson / Alvega & Co AB. All rights reserved.

## Features

- YAML-driven, one section per brand, batch any number of screenshots.
- True 4-corner perspective distort (resize + stretch + skew in one pass) using
  `PIL.Image.transform(PERSPECTIVE)` with bicubic resampling.
- Composite order: *warped screenshot → base PNG with transparent display →
  stamps → labels*.
- Stamps with arbitrary position and scale (LANCZOS resize, alpha-aware).
- Text labels with font, size, color, shadow color/offset, optional anchor
  (e.g. `"mm"` for centered).
- Optional post-processing: final crop (absolute box / centered / margins)
  and color adjustments (brightness, contrast, saturation, sharpness,
  grayscale) — at brand level or overridden per screenshot.
- Optional final resize per brand to a target output size.
- Per-brand subfolder under `dist/`, PNG output.
- Self-bootstrapping launcher (`process.sh`) that checks prerequisites, creates
  a `.venv` and installs dependencies on first run.

## Project layout

```
screenshot_builder.py     batch processor (CLI entrypoint)
editor.py                 GUI corner editor (Tk)
screenshots.yaml          default config (example)
process.sh                launcher for the batch processor
editor.sh                 launcher for the GUI editor
requirements.txt          Pillow, PyYAML, numpy, ruamel.yaml
include/
  version.py              app name / version / copyright
  logger.py               timestamped progress logger
  config_loader.py        YAML load + per-brand validation
  perspective.py          4-corner perspective warp
  postprocess.py          final crop + color adjustments
  compositor.py           base + screenshot + stamps + labels
  yaml_io.py              round-trip YAML I/O for the editor (preserves comments)
  corner_editor.py        Tk canvas widget with draggable corner handles
  builder.py              batch driver across brands
assets/                   inputs (gitignored — your own art)
  phones/                 base images (hand+phone, transparent display)
  screenshots/<brand>/    plain app screenshots
  logos/<brand>/          stamp images
  fonts/                  optional custom .ttf/.otf
dist/                     outputs (gitignored)
  <BrandName>/            one subfolder per brand
```

The subfolder layout under `assets/` is just a recommended convention —
any path that resolves under `assets/` works. Reference paths in the YAML
relative to `assets/` (e.g. `phones/hand_phone.png`, `logos/acme/logo.png`).

## Requirements

- macOS or Linux
- Python 3.10+
- Internet access on first run (to install Python deps into the local `.venv`)

## Quick start

```bash
# 1. Drop your art into assets/. For each brand referenced in screenshots.yaml
#    you need (relative to assets/):
#      - the base image (hand+phone PNG with transparent display area)
#      - one PNG per screenshot
#      - any logo / stamp PNGs
#      - any custom .ttf fonts (optional)

# 2. Edit screenshots.yaml. Most importantly, calibrate screen_corners
#    (top_left, top_right, bottom_right, bottom_left) to the display area
#    of your base image.

# 3. Run.
./process.sh                       # uses screenshots.yaml
./process.sh -c brand-x.yaml -v    # custom config, verbose
./process.sh --version
```

Outputs land in `dist/<BrandName>/<output>.png`.

## CLI

```
screenshot_builder.py [-c CONFIG] [-a ASSETS] [-o OUT] [-v] [--version]

  -c, --config   YAML config file (default: screenshots.yaml)
  -a, --assets   Assets folder    (default: assets)
  -o, --out      Dist folder      (default: dist)
  -v, --verbose  DEBUG-level logging
  --version      Print version banner and exit
```

`process.sh` forwards any flags through to the Python entrypoint.

## GUI editor (`editor.sh`)

Calibrating `screen_corners` by hand is fiddly. The GUI editor opens the
phone's base image on a canvas, lets you drag the four corners as a dashed
quad, and saves them back to the YAML — preserving comments and order.

```bash
./editor.sh                        # uses screenshots.yaml
./editor.sh -c custom.yaml         # alternate config
```

What you can do in the editor:

- Pick a phone from the dropdown (lists every entry under `phones:`).
- Drag the four red handles. Coordinate readout updates live in the status bar.
- Optional: **Load screenshot…** previews any PNG/JPEG warped behind the
  base image so you can see exactly what the final composite will look like
  while you tune the corners. The preview re-renders on mouse-release.
- **Reset corners** drops the four handles to a 15% inset of the image —
  handy starting point for a fresh phone.
- **Zoom**: `+` / `−` / `Fit` buttons in the toolbar, mouse wheel
  (zooms toward the cursor), and `Cmd/Ctrl +`, `Cmd/Ctrl −`, `Cmd/Ctrl 0`
  shortcuts. The zoom percentage is shown in the toolbar.
- **Pan** when zoomed in:
  - **Click and drag the image** (anywhere outside a corner handle).
    Cursor is a hand over the image and a pointing finger over a handle,
    so the affordance is visible before you click.
  - **Spacebar + left-drag** forces pan mode even directly on a handle.
  - **Middle-mouse drag**.
  - **Arrow keys** for fine nudging (40 px, or 5 px with Shift).
  - **Shift + mouse wheel** for horizontal scroll.
  - Plus the regular scrollbars on the canvas edges.
- **Save** writes back to `screenshots.yaml` (round-trip via `ruamel.yaml`,
  so existing comments and key order are preserved).
- **Render preview** builds a one-off composite using the current phone +
  the loaded screenshot (live corners — works even before you've hit Save)
  and writes it to `dist/_preview/<phone>.png`, then opens it. This
  bypasses the brand pipeline, so you can verify a freshly-calibrated phone
  immediately without wiring it into a brand first. The Render-preview
  button is disabled until a screenshot is loaded.

## Editor → process pipeline

The two tools have distinct jobs:

- `editor.sh` defines and calibrates *phones* (base image + four corners).
  Saving writes back to `screenshots.yaml`.
- `process.sh` runs the *brands* in `screenshots.yaml`. A brand chooses a
  phone (`phone:` or `phones:`) and supplies its own screenshots/labels/
  stamps. Calibrating a phone alone won't make `process.sh` render anything
  new — there must be a brand referencing that phone.

If you just want to see what a calibrated phone looks like with a given
screenshot, use **Render preview** in the editor. For batch production,
add or update a brand in the YAML and run `./process.sh`.

Tkinter prerequisite (one-time):

- macOS (Homebrew Python): `brew install python-tk@3.X` (matching your version)
- Ubuntu/Debian: `sudo apt install python3-tk`
- macOS system Python and python.org installers ship with Tk by default.

The launcher checks for Tkinter on startup and prints the right install
hint if it's missing.

## YAML format

The config has two top-level sections: a reusable **`phones`** registry
and one or more **`brands`**. A brand picks a phone (or a list of phones
for matrix mode) and supplies its own screenshots / labels / stamps.

```yaml
phones:
  iphone15:
    base_image: phones/iphone15.png
    screen_corners:
      top_left:     [310, 240]
      top_right:    [930, 270]
      bottom_right: [915, 1820]
      bottom_left:  [295, 1790]
  iphone15pro:
    base_image: phones/iphone15pro.png
    screen_corners: { ... }

brands:

  AcmeInc:
    phone: iphone15                       # single phone (most common)
    # phones: [iphone15, iphone15pro]     # matrix: render once per phone
    output_size: [1242, 2688]             # optional final resize
    background_color: [255, 255, 255, 0]  # optional RGBA fill behind screenshot

    screenshots:
      - source: screenshots/acme/home.png
        output: 01_home.png

        labels:
          - text: "Catch more fish"
            position: [621, 120]
            font: fonts/Inter-Bold.ttf    # optional, falls back to system font
            font_size: 84
            color: "#0B2545"
            shadow_color: "#00000055"
            shadow_offset: [3, 3]
            anchor: "mm"                  # Pillow text anchor

        stamps:
          - source: logos/acme/logo.png
            position: [40, 40]
            scale: 0.5

    # Optional post-processing applied AFTER compositing and BEFORE the
    # final `output_size` resize. Per-shot post_process overrides this.
    post_process:
      crop:
        # pick exactly one form:
        box:     [0, 80, 1242, 2768]   # absolute (left, top, right, bottom)
        # center:  [1242, 2688]        # centered crop to a target size
        # margins: [0, 80, 0, 80]      # trim N px from each edge
      adjust:
        brightness: 1.00     # 1.0 = unchanged
        contrast:   1.05
        saturation: 1.10
        sharpness:  1.00
        grayscale:  false
```

### Post-processing pipeline

Order of operations inside the compositor:

1. Warp screenshot into the four `screen_corners`.
2. Layer base image over the warped screenshot.
3. Apply stamps, then labels.
4. **`post_process.crop`** (one of `box` / `center` / `margins`).
5. **`post_process.adjust`** — `grayscale` (preserves alpha), then enhance
   `brightness` → `contrast` → `saturation` → `sharpness`. Each enhancement
   factor is multiplicative around 1.0 (`PIL.ImageEnhance` semantics):
   `1.0` is unchanged, `0.0` is the neutral image (black / no contrast /
   gray / blurred), values above `1.0` push past the original.
6. Final `output_size` resize, if specified.

`post_process` can be set on a brand (applies to every screenshot in that
brand) and/or on an individual screenshot (replaces the brand block
entirely for that one image).

### Phones × brands

- Define each phone once under `phones:` (base image + four display corners).
- A brand references a phone by name with `phone: <name>` — many brands can
  share the same phone.
- For multi-device output, set `phones: [name1, name2, ...]` on a brand;
  the builder fans out and writes one image per (phone, screenshot) pair,
  with the phone name appended to the filename
  (e.g. `01_home__iphone15pro.png`).
- Inline form is still supported: a brand may set `base_image` +
  `screen_corners` directly without using the registry.

### Calibrating `screen_corners`

The four corner points specify the destination quad inside the base image
(in base-image pixels). The screenshot is warped so its top-left/top-right/
bottom-right/bottom-left land exactly on those points. Open the base image in
any pixel-aware editor, read off the four corners of the transparent display
area, and paste them in. Sub-pixel accuracy is not required — eyeballing within
1–2 px is usually invisible.

## How the perspective warp works

`include/perspective.py` solves an 8×8 linear system from the 4 source-rectangle
↔ destination-quad point pairs and feeds the 8 coefficients to
`PIL.Image.transform(size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)`. This is a
single resampling pass, so quality is preserved — no chained resize+rotate
artefacts. The screenshot is rendered onto a transparent canvas the size of the
base image, then composited *behind* the base so the transparent display
window reveals it.

## Notes

- Output is always PNG with alpha.
- Font lookup order: explicit `font` path (relative to `assets/` or absolute)
  → common system fonts (Helvetica, Arial, DejaVu) → Pillum default bitmap.
- `assets/` and `dist/` are git-ignored on purpose — keep your brand art out
  of the source repo.
