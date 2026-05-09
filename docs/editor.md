# GUI editor (`editor.sh`)

`editor.sh` opens a Tk app with four tabs that together cover everything in
`screenshots.yaml`:

| Tab | What it's for |
| --- | ------------- |
| **Phone corners** | Calibrate `screen_corners` and `corner_radius` per phone. |
| **Configuration** | Edit brands and per-output settings: phone, screenshot, BG transform, output transform (crop/resize), labels, stamps. Live preview. |
| **Generate** | Run `process.sh` from the GUI, watch the log stream, see thumbnails of `dist/`. |
| **Assets** | Browse `assets/` (phones / backgrounds / logos / screenshots / fonts). |

A single **Save** button is overlaid on the tab strip (top-right). It writes
the current YAML state back to disk via `ruamel.yaml`, preserving comments
and key order.

```bash
./editor.sh                        # uses screenshots.yaml
./editor.sh -c custom.yaml         # alternate config
```

---

## Phone corners tab

Calibrating `screen_corners` by hand is fiddly. This tab opens the phone's
base image on a canvas and lets you drag the four corners as a dashed quad.

- Pick a phone from the dropdown (lists every entry under `phones:`).
- Drag the four red handles. Coordinate readout updates live in the status bar.
- **Corner radius** entry: type a value in base-image pixels; a dashed
  yellow outline shows the rounded shape (rendered as quadratic Beziers
  through inset points so it traces the warped quad). Persisted as the
  phone's `corner_radius`.
- **Load screenshot…** previews any PNG/JPEG warped behind the base image
  so you can see the final composite while tuning the corners. The
  preview re-renders on mouse-release.
- **Reset corners** drops the four handles to a 15% inset of the image.
- **Zoom**: `+` / `−` / `Fit` buttons in the toolbar, mouse wheel
  (zooms toward the cursor), and `Cmd/Ctrl +`, `Cmd/Ctrl −`, `Cmd/Ctrl 0`
  shortcuts.
- **Pan** when zoomed in:
  - Click and drag the image (anywhere outside a corner handle). Cursor
    is a hand over the image and a pointing finger over a handle.
  - **Spacebar + left-drag** forces pan mode even directly on a handle.
  - **Middle-mouse drag**.
  - **Arrow keys** for fine nudging (40 px, or 5 px with Shift).
  - **Shift + mouse wheel** for horizontal scroll.
  - Plus the regular scrollbars on the canvas edges.
- **Render preview** builds a one-off composite using the current phone +
  the loaded screenshot (live corners — works even before you've hit Save)
  and writes it to `dist/_preview/<phone>.png`, then opens it. Bypasses the
  brand pipeline so you can verify a freshly-calibrated phone immediately.
  Disabled until a screenshot is loaded.
- **Save** writes back to the YAML file.

---

## Configuration tab

A three-pane editor for the `brands:` section:

```
┌─ Tree (12.5%) ─┬─ Live preview (50%) ─┬─ Inspector (37.5%) ─┐
│  Brand         │   composite render    │  context-sensitive  │
│   ├ Output     │   + crop overlay      │  form for the       │
│   │  ├ Label   │   + zoom/pan          │  selected node      │
│   │  └ Stamp   │                       │                     │
│   └ Output     │                       │                     │
│  Brand         │                       │                     │
└────────────────┴───────────────────────┴─────────────────────┘
```

Dark theme throughout (`clam` + custom palette). Pane sashes are pinned at
roughly 12.5 / 50 / 37.5 % on first open.

### Tree (left pane)

- Brands → Outputs → Labels / Stamps. Each row uses an icon + name.
- Right-click context menu adds/duplicates/deletes nodes.
- Selecting any node renders the appropriate inspector form on the right
  and re-renders the preview if needed.

### Live preview (center pane)

- Renders the current output's composite using `compositor.build_composite`
  with the same code path as `process.sh`, *minus* `output_size` and
  `post_process` — those are visualised differently:
  - **Crop overlay**: a dotted red rectangle with four draggable corner
    handles. Drag a corner to update L/T/R/B (or W/H in `center` mode);
    when **Aspect lock** is on, the dragged axis leads and the other axis
    snaps to the locked ratio.
  - Resize is not previewed (no visual benefit; trust the numeric field).
- Zoom: `−` / `＋` / `Fit` buttons, mouse wheel.
- Pan: drag the image. Status bar shows `WxH · brand / output [phone]`.
- `↻` button forces an immediate re-render. Edits otherwise re-render on
  a debounce — 250 ms for most fields, 700 ms for label edits (which
  typically arrive character-by-character).

### Inspector (right pane)

The form changes based on the selected tree node:

#### Brand
- Name, default `phone`, `output_size`, `background_color` (RGBA), and
  `background_image` (path under `assets/`, with file picker).

#### Output
Multiple cards stacked top-to-bottom:

1. **Identity** — `source` screenshot path, `output` filename, optional
   per-output `phone:` override.
2. **BG transform** — only meaningful when the brand has a
   `background_image`. Card title shows the source image dimensions
   (`BG transform · offset into the 5000×3500 background`). Two fields:
   - `From top:` skip N source rows before cover-fitting.
   - `From left:` skip N source columns before cover-fitting.
   The compositor still cover-fits the remaining bg into the canvas, so
   bg always fills the canvas; offsets just pan into the source. If the
   offset is so large that fewer than 16 px remain on either axis, the
   bg is skipped entirely and `background_color` shows through (this
   safeguards against out-of-memory blow-ups when scaling tiny slivers).
3. **Output transform** — applied at Generate time, not in the preview:
   - **Crop** dropdown: `none` | `margins` | `box` | `center`. Field set
     adjusts to match the mode:
     - `none`: no fields.
     - `margins`: L/T/R/B = px to trim from each edge, plus W/H/Aspect.
     - `box`: L/T/R/B = absolute pixel rectangle to keep, plus W/H/Aspect.
     - `center`: just W/H/Aspect (centered).
   - The seven fields **stay in sync** as you type — the field with the
     cursor leads, the others recompute. Aspect can be entered as `16:9`
     or `1.778`.
   - **Aspect lock** checkbox (next to the Aspect field): when on, the
     ratio is enforced. Editing W/L/R → width leads, height = w/ratio.
     Editing H/T/B → height leads, width = h*ratio. Editing Aspect →
     becomes the new locked ratio. Dragging a corner enforces the ratio
     on the dragged axis and pins height if the box would overflow.
   - **Copy / Paste** — two tiny emoji buttons (📋 / 📥) appear in the
     Crop header in `box` mode only. Copy puts a compact JSON payload
     on the clipboard:
     ```
     {"box":[100,200,1190,2596],"resize":[1290,2796]}
     ```
     Paste accepts that JSON or bare CSV (`100,200,1190,2596` or
     `100,200,1190,2596|1290,2796`), switches mode to `box`, and
     repopulates all fields. Paste is auto-disabled when the clipboard
     doesn't contain a valid payload (re-checked every ~700 ms).
   - **Resize** row: `W` and `H` entries. Either or both. Blank = no resize.

#### Label
- `text`, position `[x, y]`, `font_size`, `color`, `anchor` (Pillow
  anchor codes from a dropdown — `mm`, `lt`, `rt`, etc.). Edits debounce
  the preview render at 700 ms so typing isn't sluggish.

#### Stamp
- `source` (logo path, with file picker), `position`, `scale`.

### Saving

The single **Save** button on the tab strip persists everything to the YAML
via `ruamel.yaml` round-trip helpers in `include/brand_io.py` and
`include/yaml_io.py`. The tab strip's title gets a `*` suffix while there
are unsaved edits.

---

## Generate tab

- Big **Run** button shells out to `process.sh`. Stdout/stderr stream into
  a scrollable text widget below.
- When the run finishes, the bottom panel populates with thumbnails of
  every PNG under `dist/`, grouped by brand. Click a thumbnail to open the
  full image in the OS default viewer.
- Use this to verify a config change without leaving the editor.

---

## Assets tab

Browse the contents of `assets/` by category:

- **Phones** — `assets/phones/`
- **Backgrounds** — `assets/backgrounds/`
- **Logos** — `assets/logos/<brand>/`
- **Screenshots** — `assets/screenshots/<brand>/`
- **Fonts** — `assets/fonts/`

Each row shows a thumbnail (where applicable), filename, and dimensions.
Useful as a quick "what do I have" reference while editing brands.
