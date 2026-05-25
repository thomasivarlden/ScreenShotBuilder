# Screenshot Builder

Batch-generate App Store / Play Store marketing screenshots locally from a YAML
recipe. Headless CLI, Python, high-quality image manipulation via Pillow,
optional Tk GUI editor, and an Android-emulator capture orchestrator that
feeds the pipeline raw screenshots straight from a Flutter app.

For each *output* you define, the tool takes a base image (e.g. a hand holding
a phone with a transparent display area), warps a plain screenshot into the
four corners of that display using a true perspective transform, and finally
composites optional stamps (logos) and text labels (with shadow) on top.

- **Author:** Thomas F Abrahamsson, Alvega & Co AB · `Thomas@alvega.company`
- **License:** © Thomas F Abrahamsson / Alvega & Co AB. All rights reserved.

## Three tools, one repo

| Tool | Entry point | Purpose |
| ---- | ----------- | ------- |
| Batch processor | `process.sh` → `screenshot_builder.py` | Read `screenshots.yaml`, render every brand × output to `dist/` |
| GUI editor | `editor.sh` → `editor.py` | Calibrate phones, edit brands/outputs, preview composites, generate, browse assets |
| Capture orchestrator | `capture.sh` → `capture.py` | Drive a running Android emulator over ADB to log into each brand's Flutter app and save raw screenshots into `assets/screenshots/<brand>/` |

The two human-facing tools (`editor.sh`, `capture.sh`) feed YAML and PNGs that
the headless `process.sh` consumes.

- See [docs/editor.md](docs/editor.md) for the full GUI editor reference
  (Phone corners, Configuration, Generate, Assets tabs).
- See [docs/capture.md](docs/capture.md) for the Android capture orchestrator.

## Features

- YAML-driven, brand-grouped, batch any number of outputs.
- True 4-corner perspective distort using `PIL.Image.transform(PERSPECTIVE)`
  with bicubic resampling — single-pass resize+stretch+skew, no chained
  resize+rotate artefacts.
- Composite order: *background → warped screenshot → base PNG with transparent
  display → stamps → labels*.
- Optional **rounded screenshot corners** — phones can declare a
  `corner_radius` (in base-image px) so app screenshots get a soft rounded
  mask before being warped onto the display.
- Optional **brand background image** — cover-fit to the canvas, with an
  optional per-output offset (`background_offset.top` / `.left`) that pans
  into the source image without scaling artifacts.
- **Per-output phone selection** — each output can pick its own `phone:`
  (or fall back to the brand's `phone:`/`phones:`), so one brand can mix
  iPhone, Samsung, plain renders, etc. in a single config.
- Stamps (alpha-aware, scaleable) and text labels (font, size, color, shadow,
  Pillow anchor).
- Per-output post-processing: crop (box / center / margins), resize
  (width and/or height), color adjust (brightness, contrast, saturation,
  sharpness, grayscale).
- Optional final per-brand `output_size` resize.
- Self-bootstrapping launchers (`process.sh`, `editor.sh`, `capture.sh`)
  that check prerequisites and create a local `.venv` on first run.

## Project layout

```
screenshot_builder.py     batch processor (CLI entrypoint)
editor.py                 GUI editor (Tk; 4-tab notebook)
capture.py                capture orchestrator (CLI)
screenshots.yaml          rendering config (phones + brands)
capture.yaml              capture config (brand → flavor / app_id)
secrets.example.yaml      template for capture/secrets.yaml (gitignored)
process.sh                launcher for the batch processor
editor.sh                 launcher for the GUI editor
capture.sh                launcher for the capture orchestrator
requirements.txt          Pillow, PyYAML, numpy, ruamel.yaml

include/                  pipeline + GUI internals
  version.py              app name / version / copyright
  logger.py               timestamped progress logger
  config_loader.py        YAML load + per-brand validation, phone resolution
  perspective.py          4-corner perspective warp
  postprocess.py          crop + resize + adjust pipeline
  compositor.py           background + warped screenshot + base + stamps + labels
  builder.py              batch driver (per-output mode + legacy matrix mode)
  yaml_io.py              round-trip YAML I/O for phones (preserves comments)
  brand_io.py             round-trip YAML I/O for the brands section
  corner_editor.py        Tk canvas widget with draggable corner handles
  brand_editor.py         Configuration tab (3-pane brand/output editor)
  generate_tab.py         Generate tab (runs process.sh, shows thumbnails)
  assets_tab.py           Assets tab (browse phones/backgrounds/logos/screenshots/fonts)

capture/                  Android-emulator capture package
  adb.py                  thin adb wrapper (tap/swipe/type/screencap/wait_text)
  emulator.py             AVD discovery + boot
  flow.py                 step runner
  flows.py                screen flows (login, home, …) — registered in SCREENS

assets/                   inputs — Git submodule pointing at the private
                          ScreenShotBuilder-assets repo (LFS-tracked)
  phones/                 base images (hand+phone, transparent display)
  backgrounds/            optional background images per brand
  screenshots/<brand>/    plain app screenshots
  logos/<brand>/          stamp images
  fonts/                  optional custom .ttf/.otf
dist/                     outputs (gitignored)
  index.html              static image browser of everything in dist/
  <BrandName>/            one subfolder per brand
    <os>/<form>/<lang>/   e.g. ios/phone/en/ — one upload-ready set per folder
    Clean/<os>/<form>/<lang>/   transparent phone-only twins (suffix _Clean)
```

Outputs are grouped by **device class and language** so each leaf folder maps
to one App Store / Play Console upload slot: `os` is `ios`/`android` (falling
back to `other`), `form` is `phone`/`tablet`. The bucket is taken from each
phone's `platform:`/`form:` keys, falling back to sniffing the phone name.
A transparent **Clean** variant (phone + screenshot only, no background, labels
or stamps) is rendered for every output by default; disable with `--no-clean`.

The subfolder layout under `assets/` is just a recommended convention — any
path that resolves under `assets/` works. Reference paths in the YAML
relative to `assets/` (e.g. `phones/hand_phone.png`, `logos/acme/logo.png`).
See [Cloning](#cloning) below for how to fetch the assets submodule.

## Requirements

- macOS or Linux
- Python 3.10+
- Internet access on first run (to install Python deps into the local `.venv`)
- For the GUI editor: Tkinter (see *Tkinter prerequisite* below)
- For the capture orchestrator: a working Android SDK (`adb`, `emulator`)
  and `fvm` if you use `--rebuild`
- For brand assets: `git-lfs` (the `assets/` directory is a private submodule
  with LFS-tracked phone/logo/background PNGs)

### Cloning

The `assets/` directory is a Git submodule pointing to a **private** repo
that holds the brand-specific binary assets via Git LFS. To get a working
checkout in one step:

```bash
brew install git-lfs && git lfs install         # one-time
git clone --recurse-submodules https://github.com/thomasivarlden/ScreenShotBuilder.git
```

If you already cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

You need access to the private `ScreenShotBuilder-assets` repo for the
submodule fetch to succeed. Without it the code still runs — it just
can't render anything that references missing files.

## Quick start

```bash
# 1. Drop your art into assets/. For each brand referenced in screenshots.yaml
#    you need (relative to assets/):
#      - the base image (hand+phone PNG with transparent display area)
#      - one PNG per screenshot
#      - any logo / stamp PNGs
#      - any custom .ttf fonts (optional)

# 2. Edit screenshots.yaml. The GUI editor (./editor.sh) is the easy way —
#    calibrate phones in the Phone corners tab, then build outputs in the
#    Configuration tab.

# 3. Render.
./process.sh                       # uses screenshots.yaml
./process.sh -c brand-x.yaml -v    # custom config, verbose
./process.sh --version
```

Outputs land in `dist/<BrandName>/<os>/<form>/<lang>/<NN_name>.png`, with
transparent twins in `dist/<BrandName>/Clean/...` and a browsable
`dist/index.html` gallery.

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

### Tkinter prerequisite (one-time, GUI only)

- macOS (Homebrew Python): `brew install python-tk@3.X` (matching your version)
- Ubuntu/Debian: `sudo apt install python3-tk`
- macOS system Python and python.org installers ship with Tk by default.

The launcher checks for Tkinter on startup and prints the right install hint
if it's missing.

## YAML format

The config has two top-level sections: a reusable **`phones`** registry and
one or more **`brands`**. A brand groups one or more *outputs*; each output
references a phone, a screenshot, and any labels/stamps.

```yaml
phones:
  iphone15:
    base_image: phones/iphone15.png
    corner_radius: 60                     # optional, in base-image px
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
    phone: iphone15                       # default phone for this brand
    # phones: [iphone15, iphone15pro]     # legacy matrix: render every output once per phone
    output_size: [1242, 2688]             # optional final resize
    background_color: [255, 255, 255, 0]  # RGBA fill behind the screenshot
    background_image: backgrounds/acme.jpg  # optional, cover-fits the canvas

    screenshots:                          # one entry per output
      - source: screenshots/acme/home.png
        output: 01_home.png
        phone: iphone15pro                # optional: override per output

        # Optional: pan into the brand background image (skip N source
        # columns/rows BEFORE cover-fitting it to the canvas).
        background_offset:
          left: 200
          top:  0

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
        # final per-brand `output_size` resize. Per-output post_process
        # overrides any brand-level block entirely.
        post_process:
          crop:
            # pick exactly one form:
            box:     [0, 80, 1242, 2768]   # absolute (left, top, right, bottom)
            # center:  [1242, 2688]        # centered crop to a target size
            # margins: [0, 80, 0, 80]      # trim N px from each edge
          resize:
            width:  1242                   # either or both; missing dim
            height: 2688                   # preserves aspect
          adjust:
            brightness: 1.00               # 1.0 = unchanged
            contrast:   1.05
            saturation: 1.10
            sharpness:  1.00
            grayscale:  false
```

### Compositor pipeline

Order of operations inside `compositor.py`:

1. Fill canvas with `background_color`.
2. If a brand `background_image` exists: skip `background_offset.left` /
   `.top` source columns/rows (per-output, default 0), then cover-fit the
   remainder to the canvas. If the offset eats too much of the source
   (less than 16 px remaining on either axis), the bg is skipped and
   `background_color` shows through.
3. Apply optional `corner_radius` mask to the screenshot, then warp into
   the phone's `screen_corners` quad.
4. Layer base image over the warped screenshot.
5. Apply stamps, then labels.
6. **`post_process.crop`** (one of `box` / `center` / `margins`).
7. **`post_process.resize`** (width and/or height; missing dim preserves
   aspect).
8. **`post_process.adjust`** — `grayscale` (preserves alpha), then enhance
   `brightness` → `contrast` → `saturation` → `sharpness`. Each enhancement
   factor is multiplicative around 1.0 (`PIL.ImageEnhance` semantics):
   `1.0` is unchanged, `0.0` is the neutral image (black / no contrast /
   gray / blurred), values above `1.0` push past the original.
9. Final per-brand `output_size` resize, if specified.

`post_process` can be set on a brand (applies to every output in that brand)
and/or on an individual output (replaces the brand block entirely for that
output).

### Phones × brands × outputs

- Define each phone once under `phones:` (base image + four display corners +
  optional corner radius).
- A brand sets a default phone with `phone: <name>`. Every output under the
  brand uses that phone unless it sets its own `phone:` field.
- **Per-output mode** (recommended): give each `screenshots:` entry its own
  `phone:` to mix devices in one brand. Output filenames are taken from
  `output:` as-is — no phone suffix is appended.
- **Legacy matrix mode**: set `phones: [name1, name2, ...]` on the brand and
  leave outputs without a `phone:` field; the builder fans out and writes one
  image per `(phone, output)` pair, with the phone name appended to the
  filename (e.g. `01_home__iphone15pro.png`).
- Inline form is still supported: a brand may set `base_image` +
  `screen_corners` directly without using the registry.

### Calibrating `screen_corners`

The four corner points specify the destination quad inside the base image
(in base-image pixels). The screenshot is warped so its top-left/top-right/
bottom-right/bottom-left land exactly on those points. Use the **Phone
corners** tab in `editor.sh` (drag four red handles, see live screenshot
preview, optionally type a `corner_radius` and see the rounded outline).
Sub-pixel accuracy is not required — eyeballing within 1–2 px is invisible.

## How the perspective warp works

`include/perspective.py` solves an 8×8 linear system from the 4
source-rectangle ↔ destination-quad point pairs and feeds the 8 coefficients
to `PIL.Image.transform(size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)`. This
is a single resampling pass, so quality is preserved — no chained
resize+rotate artefacts. The screenshot is rendered onto a transparent canvas
the size of the base image, then composited *behind* the base so the
transparent display window reveals it.

## Notes

- Output is always PNG with alpha.
- Font lookup order: explicit `font` path (relative to `assets/` or absolute)
  → common system fonts (Helvetica, Arial, DejaVu) → Pillow default bitmap.
- `dist/` and `secrets.yaml` are git-ignored on purpose — keep generated
  output and PUKs out of the source repo. `assets/` lives in a separate
  **private** submodule (`ScreenShotBuilder-assets`) so brand art stays
  out of the public source repo while still being version-pinned to the
  code.
