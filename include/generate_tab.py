"""Generate tab — launches the build, streams progress, shows result thumbnails."""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from PIL import Image, ImageTk


THUMB_MAX = (220, 320)   # max thumbnail w, h
COLUMNS = 4


class GenerateTab(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        repo_root: Path,
        config_path: Path,
        assets_dir: Path,
        on_request_save: Callable[[], bool],
    ) -> None:
        super().__init__(parent)
        self.repo_root = repo_root
        self.config_path = config_path
        self.assets_dir = assets_dir
        self.dist_dir = (repo_root / "dist").resolve()
        self.on_request_save = on_request_save
        self._proc: subprocess.Popen | None = None
        self._log_queue: queue.Queue[str | None] = queue.Queue()
        self._thumb_refs: list[ImageTk.PhotoImage] = []  # keep refs alive

        self._build_ui()

    # ---------- UI ------------------------------------------------------

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 8))
        toolbar.pack(side="top", fill="x")

        self.run_btn = ttk.Button(toolbar, text="Generate", command=self._start)
        self.run_btn.pack(side="left")

        self.stop_btn = ttk.Button(toolbar, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)

        ttk.Button(toolbar, text="Open output folder", command=self._open_dist)\
            .pack(side="left", padx=12)
        ttk.Button(toolbar, text="Refresh thumbnails", command=self._refresh_thumbnails)\
            .pack(side="left")

        self.status_var = tk.StringVar(value="Idle. Click Generate to build all brands.")
        ttk.Label(toolbar, textvariable=self.status_var, foreground="#444")\
            .pack(side="left", padx=12)

        # Vertical paned: log on top, thumbnails below.
        paned = ttk.Panedwindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # ---- Log pane ----
        log_frame = ttk.Frame(paned)
        paned.add(log_frame, weight=1)
        ttk.Label(log_frame, text="Build log", font=("", 10, "bold")).pack(anchor="w")
        log_inner = ttk.Frame(log_frame)
        log_inner.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_inner, height=10, wrap="none",
                                bg="#1e1e22", fg="#e0e0e0",
                                insertbackground="#e0e0e0", state="disabled")
        log_scroll = ttk.Scrollbar(log_inner, orient="vertical", command=self.log_text.yview)
        self.log_text.config(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        # ---- Thumbnails pane ----
        thumbs_outer = ttk.Frame(paned)
        paned.add(thumbs_outer, weight=2)
        ttk.Label(thumbs_outer, text="Output", font=("", 10, "bold")).pack(anchor="w")

        canvas_frame = ttk.Frame(thumbs_outer)
        canvas_frame.pack(fill="both", expand=True)
        self.thumb_canvas = tk.Canvas(canvas_frame, bg="#2a2a2e", highlightthickness=0)
        thumb_scroll = ttk.Scrollbar(canvas_frame, orient="vertical",
                                     command=self.thumb_canvas.yview)
        self.thumb_canvas.config(yscrollcommand=thumb_scroll.set)
        self.thumb_canvas.pack(side="left", fill="both", expand=True)
        thumb_scroll.pack(side="right", fill="y")

        self.thumb_frame = ttk.Frame(self.thumb_canvas)
        self._thumb_window = self.thumb_canvas.create_window((0, 0), window=self.thumb_frame,
                                                             anchor="nw")
        self.thumb_frame.bind(
            "<Configure>",
            lambda _e: self.thumb_canvas.configure(scrollregion=self.thumb_canvas.bbox("all")),
        )
        # Mousewheel scrolling for the thumbs canvas.
        self.thumb_canvas.bind("<MouseWheel>",
                               lambda e: self.thumb_canvas.yview_scroll(-1 * (1 if e.delta > 0 else -1), "units"))

        # Initial thumbnail population (in case dist/ already has images).
        self.after(100, self._refresh_thumbnails)

    # ---------- log helpers --------------------------------------------

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ---------- run / stop ---------------------------------------------

    def _start(self) -> None:
        if self._proc is not None:
            return
        # Make sure the user's current edits are persisted to YAML before
        # the build reads it.
        if not self.on_request_save():
            return

        self._clear_log()
        self.status_var.set("Running…")
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

        cmd = [
            sys.executable,
            str(self.repo_root / "screenshot_builder.py"),
            "-c", str(self.config_path),
            "-a", str(self.assets_dir),
            "-o", str(self.dist_dir),
        ]
        self._append_log(f"$ {' '.join(cmd)}\n\n")

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(self.repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            messagebox.showerror("Generate", f"Failed to launch builder: {exc}", parent=self)
            self._proc = None
            self.run_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self.status_var.set("Failed to launch.")
            return

        threading.Thread(target=self._reader_thread, daemon=True).start()
        self.after(100, self._drain_queue)

    def _reader_thread(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            self._log_queue.put(line)
        self._proc.stdout.close()
        rc = self._proc.wait()
        self._log_queue.put(f"\n[exit {rc}]\n")
        self._log_queue.put(None)  # sentinel: build finished

    def _drain_queue(self) -> None:
        try:
            while True:
                item = self._log_queue.get_nowait()
                if item is None:
                    self._on_finished()
                    return
                self._append_log(item)
        except queue.Empty:
            pass
        if self._proc is not None:
            self.after(100, self._drain_queue)

    def _on_finished(self) -> None:
        rc = self._proc.returncode if self._proc else None
        self._proc = None
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        if rc == 0:
            self.status_var.set("Done.")
        else:
            self.status_var.set(f"Finished with exit code {rc}.")
        self._refresh_thumbnails()

    def _stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self.status_var.set("Stopping…")
        except OSError:
            pass

    # ---------- thumbnails ---------------------------------------------

    def _refresh_thumbnails(self) -> None:
        for child in self.thumb_frame.winfo_children():
            child.destroy()
        self._thumb_refs.clear()

        if not self.dist_dir.is_dir():
            ttk.Label(self.thumb_frame,
                      text="(no dist/ folder yet — run Generate first)",
                      foreground="#888").grid(row=0, column=0, padx=8, pady=8, sticky="w")
            return

        files = sorted(p for p in self.dist_dir.rglob("*.png") if "_preview" not in p.parts)
        if not files:
            ttk.Label(self.thumb_frame,
                      text="(no PNG output found under dist/)",
                      foreground="#888").grid(row=0, column=0, padx=8, pady=8, sticky="w")
            return

        for i, path in enumerate(files):
            r, c = divmod(i, COLUMNS)
            self._add_thumb(path, r, c)

    def _add_thumb(self, path: Path, row: int, col: int) -> None:
        try:
            img = Image.open(path)
            img.thumbnail(THUMB_MAX, Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
        except Exception as exc:  # noqa: BLE001
            ttk.Label(self.thumb_frame, text=f"{path.name}\n[error: {exc}]",
                      foreground="#a44").grid(row=row, column=col, padx=8, pady=8)
            return
        self._thumb_refs.append(photo)

        cell = ttk.Frame(self.thumb_frame, padding=4)
        cell.grid(row=row, column=col, padx=4, pady=4, sticky="n")
        lbl = tk.Label(cell, image=photo, bg="#1f1f23", cursor="hand2")
        lbl.pack()
        lbl.bind("<Button-1>", lambda _e, p=path: self._open_path(p))
        try:
            rel = path.relative_to(self.dist_dir)
        except ValueError:
            rel = path.name
        ttk.Label(cell, text=str(rel), foreground="#ccc",
                  wraplength=THUMB_MAX[0], justify="center")\
            .pack(pady=(2, 0))

    # ---------- open helpers -------------------------------------------

    def _open_dist(self) -> None:
        self.dist_dir.mkdir(parents=True, exist_ok=True)
        self._open_path(self.dist_dir)

    @staticmethod
    def _open_path(path: Path) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(path)])
            elif sys.platform.startswith("win"):
                subprocess.Popen(["explorer", str(path)])
            else:
                webbrowser.open(path.as_uri())
        except Exception:
            webbrowser.open(path.as_uri())
