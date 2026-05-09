# Capture orchestrator (`capture.sh`)

Drives a running Android emulator over `adb` to log into each brand's Flutter
app and capture screenshots into `assets/screenshots/<brand>/<screen>.png`.
The captures land directly under `assets/screenshots/`, ready for the
existing `screenshot_builder.py` pipeline to reference from `screenshots.yaml`.

```bash
./capture.sh                                # all brands × all screens
./capture.sh --brand fishy                  # one brand
./capture.sh --screen home                  # one screen, all brands
./capture.sh --brand fishy --rebuild        # reinstall the APK first
./capture.sh --start-emulator               # boot the first AVD if none running
./capture.sh --start-emulator Pixel_7_API_34
./capture.sh --list                         # list brands + screens, exit
./capture.sh --list-avds                    # list installed AVDs, exit
```

The launcher creates/uses the same `.venv` as the other tools.

## Prerequisites

- A working Android SDK at `~/Library/Android/sdk` (the Homebrew Android SDK
  on macOS is broken in some setups; `capture/emulator.py` hardcodes the
  standard SDK location).
- An AVD installed in that SDK (`emulator -list-avds`). `--list-avds`
  surfaces the same list.
- Each brand's APK installed on the running emulator. Use `--rebuild` to
  install/reinstall via `fvm flutter install --flavor <flavor>` first.
- For `--rebuild`: `fvm` on `PATH` and a `flutter_project` path in
  `capture.yaml` pointing to your Flutter app.

## Configuration

### `capture.yaml`

```yaml
brands:
  fishy:
    app_id: nu.fishy.app
    flavor: fishy
    dart_defines: {}              # optional --dart-define=K=V pairs

  big5:
    app_id: nu.fishy.app.big5
    flavor: big5

  sportfiskarna:
    app_id: se.sportfiskarna.fishy.app
    flavor: sportfiskarna

# Used only when --rebuild is passed.
flutter_project: ~/Projects/fishy_app

# Captures land at <output_dir>/<brand>/<screen>.png. Default places them
# inside assets/screenshots so screenshot_builder.py can reference them
# directly from screenshots.yaml.
output_dir: assets/screenshots
```

### `secrets.yaml` (gitignored)

Per-brand PUKs used by the login flow. Copy `secrets.example.yaml` to
`secrets.yaml` and fill in real values:

```yaml
puks:
  fishy: "461968"
  big5: "0000"
  sportfiskarna: "0000"
```

If `secrets.yaml` is missing or a brand has no PUK, login steps that need
a PUK are skipped.

## Architecture

```
capture.py                  CLI entrypoint, argument parsing, brand loop
capture/
  adb.py                    thin wrapper around `adb` shell
                            (devices, screen_size, tap, swipe, type_text,
                             key, screencap, pm_clear, launch, force_stop,
                             ui_dump_text, wait_text)
  emulator.py               AVD discovery + boot
                            (sdk_root, list_avds, start)
  flow.py                   Step + Context dataclasses, run_flow()
  flows.py                  named flows registered in SCREENS
                            (home, _login helper, …)
```

The `SCREENS` dict in `capture/flows.py` is the registry of capturable
screens. To add a new screen, write a function `def my_screen(puk) -> list[Step]:`
and add it to `SCREENS`:

```python
SCREENS: dict[str, FlowBuilder] = {
    "home": home,
    "settings": settings,        # add yours here
}
```

A `Step` is just a callable that takes the `Context` (app_id, out_path,
puk) and performs adb actions. `flow.run_flow` walks the list, with
shared error handling and `force_stop(app_id)` cleanup at the end.

## Typical workflow

1. Start an emulator (or pass `--start-emulator`).
2. Install the brand's APK once (or pass `--rebuild` for each capture run).
3. `./capture.sh --brand fishy --screen home` — drives login + navigation,
   takes a `screencap`, saves it under `assets/screenshots/fishy/home.png`.
4. Open `editor.sh`, switch to **Configuration**, point an output's
   `source` at the new screenshot, and **Save**.
5. **Generate** to render the marketing composite.

## Troubleshooting

- **`No emulator/device found`** — start an emulator first
  (`emulator @AVDName &` or `./capture.sh --start-emulator`).
- **`Unknown brand …`** — the brand ID isn't in `capture.yaml`. Use
  `--list` to see the registered set.
- **`flutter install failed for flavor …`** (with `--rebuild`) — the
  `flavor:` in `capture.yaml` doesn't match a flavor declared in the
  Flutter project's `android/app/build.gradle`. Verify with
  `cd $flutter_project && fvm flutter build apk --flavor <flavor>`.
- **Login flow stalls** — the brand's PUK is wrong or missing in
  `secrets.yaml`. Steps that wait on UI text time out after ~15 s
  (`adb.wait_text` default).
- **SDK not found** — `capture/emulator.py` looks at
  `~/Library/Android/sdk`. If yours lives elsewhere, fix `sdk_root()`
  or symlink the directory.
