"""Translations tab — manage languages and translate label strings."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable, Dict, List

from .translations import (
    DEFAULT_SETTINGS,
    collect_label_texts,
    default_data,
    get_settings,
    load_translations,
    save_translations,
)


# ---------------------------------------------------------------------------
# Inline cell editor for Treeview
# ---------------------------------------------------------------------------

class _CellEditor:
    """Overlays a temporary Entry on a Treeview cell for in-place editing."""

    def __init__(
        self,
        tree: ttk.Treeview,
        item: str,
        col_id: str,
        current: str,
        on_commit: Callable[[str, str, str], None],
    ) -> None:
        bbox = tree.bbox(item, col_id)
        if not bbox:
            return
        x, y, w, h = bbox

        self._tree = tree
        self._item = item
        self._col_id = col_id
        self._on_commit = on_commit

        self._var = tk.StringVar(value=current)
        self._entry = tk.Entry(tree, textvariable=self._var, relief="flat",
                               highlightthickness=1, highlightcolor="#4ea1ff",
                               highlightbackground="#4ea1ff",
                               bg="#2c2c32", fg="#e6e6ea", insertbackground="#e6e6ea")
        self._entry.place(x=x, y=y, width=w, height=h)
        self._entry.focus_set()
        self._entry.select_range(0, "end")
        self._entry.bind("<Return>", self._commit)
        self._entry.bind("<Tab>", self._commit)
        self._entry.bind("<Escape>", self._cancel)
        self._entry.bind("<FocusOut>", self._commit)

    def _commit(self, _event: Any = None) -> None:
        value = self._var.get()
        self._entry.destroy()
        self._on_commit(self._item, self._col_id, value)

    def _cancel(self, _event: Any = None) -> None:
        self._entry.destroy()


# ---------------------------------------------------------------------------
# Translations Tab
# ---------------------------------------------------------------------------

class TranslationsTab(ttk.Frame):
    """Editor tab: language management + string translation table."""

    def __init__(
        self,
        parent: tk.Widget,
        config_getter: Callable[[], Dict[str, Any]],
        translations_path: Path,
        on_dirty: Callable[[], None],
        on_translation_change: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_getter = config_getter
        self._translations_path = translations_path
        self._on_dirty = on_dirty
        self._on_translation_change = on_translation_change

        self._data: Dict[str, Any] = load_translations(translations_path)
        self._active_editor: _CellEditor | None = None

        self._build_ui()
        self._refresh_table()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_data(self) -> Dict[str, Any]:
        # Flush live widget values into _data before returning.
        self._data.setdefault("settings", {})
        self._data["settings"]["base_language"] = self._base_lang_var.get().strip() or "en"
        self._data["settings"]["label_align"] = self._align_var.get()
        return self._data

    def reload_from_disk(self) -> None:
        self._data = load_translations(self._translations_path)
        s = get_settings(self._data)
        self._base_lang_var.set(s.get("base_language", "en"))
        self._align_var.set(s.get("label_align", "center"))
        self._rebuild_columns()
        self._refresh_table()

    def sync_strings_from_config(self) -> None:
        """Add any new label texts found in the current config (never removes)."""
        config = self._config_getter()
        strings = self._data.setdefault("strings", {})
        for text in collect_label_texts(config):
            strings.setdefault(text, {})
        self._refresh_table()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ---- Top: language management -----------------------------------
        lang_frame = ttk.LabelFrame(self, text="Languages", padding=(8, 4))
        lang_frame.pack(side="top", fill="x", padx=8, pady=(8, 4))

        self._lang_list = tk.Listbox(
            lang_frame, height=4, selectmode="browse",
            bg="#26262b", fg="#e6e6ea", selectbackground="#274a73",
            activestyle="none", relief="flat", highlightthickness=0,
            font=("", 11),
        )
        self._lang_list.pack(side="left", fill="x", expand=True)
        self._lang_list.bind("<<ListboxSelect>>", self._on_lang_select)

        btn_col = ttk.Frame(lang_frame)
        btn_col.pack(side="left", padx=(8, 0))
        ttk.Button(btn_col, text="Add…", command=self._add_language).pack(fill="x", pady=2)
        ttk.Button(btn_col, text="Remove", command=self._remove_language).pack(fill="x", pady=2)
        self._toggle_btn = ttk.Button(btn_col, text="Enable / Disable",
                                      command=self._toggle_language)
        self._toggle_btn.pack(fill="x", pady=2)

        self._lang_status = ttk.Label(lang_frame, text="", foreground="#9a9aa3")
        self._lang_status.pack(side="left", padx=12)

        self._rebuild_lang_list()

        # ---- Settings ---------------------------------------------------
        settings_frame = ttk.LabelFrame(self, text="Settings", padding=(8, 4))
        settings_frame.pack(side="top", fill="x", padx=8, pady=(0, 4))

        ttk.Label(settings_frame, text="Base language:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        s = get_settings(self._data)
        self._base_lang_var = tk.StringVar(value=s.get("base_language", "en"))
        base_lang_entry = ttk.Entry(settings_frame, textvariable=self._base_lang_var, width=8)
        base_lang_entry.grid(row=0, column=1, sticky="w")
        self._base_lang_var.trace_add("write", lambda *_: self._on_setting_change())

        ttk.Label(settings_frame, text="   Foreign label alignment:").grid(
            row=0, column=2, sticky="w", padx=(12, 6))
        self._align_var = tk.StringVar(value=s.get("label_align", "center"))
        align_frame = ttk.Frame(settings_frame)
        align_frame.grid(row=0, column=3, sticky="w")
        for value, label_text in (("left", "Left (as-is)"), ("center", "Center"), ("right", "Right")):
            ttk.Radiobutton(
                align_frame, text=label_text, variable=self._align_var, value=value,
                command=self._on_setting_change,
            ).pack(side="left", padx=6)

        ttk.Label(
            settings_frame,
            text="Center/Right: translated text is aligned to the measured English text boundary.",
            foreground="#9a9aa3",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 0))

        # ---- Middle: toolbar for strings --------------------------------
        bar = ttk.Frame(self, padding=(8, 0))
        bar.pack(side="top", fill="x")
        ttk.Button(bar, text="Sync strings from config",
                   command=self._sync_and_refresh).pack(side="left")
        self._status_label = ttk.Label(bar, text="", foreground="#9a9aa3")
        self._status_label.pack(side="left", padx=12)

        # ---- Main: string table -----------------------------------------
        table_frame = ttk.Frame(self)
        table_frame.pack(side="top", fill="both", expand=True, padx=8, pady=(4, 8))

        self._tree = ttk.Treeview(table_frame, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self._tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        hsb.pack(side="bottom", fill="x")
        vsb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)

        self._tree.bind("<Button-1>", self._on_table_click)
        self._tree.bind("<MouseWheel>",
                        lambda e: self._tree.yview_scroll(-1 if e.delta > 0 else 1, "units"))

        self._rebuild_columns()

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------

    def _on_setting_change(self) -> None:
        self._data.setdefault("settings", {})
        self._data["settings"]["base_language"] = self._base_lang_var.get().strip() or "en"
        self._data["settings"]["label_align"] = self._align_var.get()
        self._on_dirty()

    # ------------------------------------------------------------------
    # Language list helpers
    # ------------------------------------------------------------------

    def _rebuild_lang_list(self) -> None:
        self._lang_list.delete(0, "end")
        for lang in self._data.get("languages", []):
            enabled = lang.get("enabled", True)
            marker = "✓" if enabled else "○"
            self._lang_list.insert("end", f"  {marker}  {lang['code']}  —  {lang['name']}")
        self._update_lang_status()

    def _update_lang_status(self) -> None:
        langs = self._data.get("languages", [])
        enabled = [l for l in langs if l.get("enabled", True)]
        non_en = [l for l in enabled if l["code"] != "en"]
        self._lang_status.configure(
            text=f"{len(langs)} language(s)  ·  {len(enabled)} enabled  ·  {len(non_en)} will be built"
        )

    def _on_lang_select(self, _event: Any = None) -> None:
        pass

    def _selected_lang_index(self) -> int | None:
        sel = self._lang_list.curselection()
        return sel[0] if sel else None

    def _add_language(self) -> None:
        code = simpledialog.askstring(
            "Add language",
            "Enter BCP-47 language code (e.g. fr, de, ja):",
            parent=self,
        )
        if not code:
            return
        code = code.strip().lower()
        langs = self._data.setdefault("languages", [])
        if any(l["code"] == code for l in langs):
            messagebox.showinfo("Add language", f"'{code}' is already in the list.", parent=self)
            return
        name = simpledialog.askstring(
            "Add language",
            f"Display name for '{code}':",
            parent=self,
        ) or code
        langs.append({"code": code, "name": name.strip(), "enabled": True})
        self._rebuild_lang_list()
        self._rebuild_columns()
        self._refresh_table()
        self._on_dirty()

    def _remove_language(self) -> None:
        idx = self._selected_lang_index()
        if idx is None:
            return
        langs = self._data.get("languages", [])
        lang = langs[idx]
        if lang["code"] == "en":
            messagebox.showinfo("Remove", "Cannot remove the base English language.", parent=self)
            return
        if not messagebox.askyesno(
            "Remove language",
            f"Remove '{lang['code']}' ({lang['name']}) and all its translations?",
            parent=self,
        ):
            return
        langs.pop(idx)
        # Remove translations for this code.
        for translations in self._data.get("strings", {}).values():
            translations.pop(lang["code"], None)
        self._rebuild_lang_list()
        self._rebuild_columns()
        self._refresh_table()
        self._on_dirty()

    def _toggle_language(self) -> None:
        idx = self._selected_lang_index()
        if idx is None:
            return
        lang = self._data.get("languages", [])[idx]
        if lang["code"] == "en":
            messagebox.showinfo("Toggle", "English (base language) cannot be disabled.", parent=self)
            return
        lang["enabled"] = not lang.get("enabled", True)
        self._rebuild_lang_list()
        self._rebuild_columns()
        self._refresh_table()
        self._on_dirty()

    # ------------------------------------------------------------------
    # Table helpers
    # ------------------------------------------------------------------

    def _non_en_languages(self) -> List[Dict[str, Any]]:
        return [l for l in self._data.get("languages", []) if l["code"] != "en"]

    def _rebuild_columns(self) -> None:
        cols = ["english"] + [l["code"] for l in self._non_en_languages()]
        self._tree.configure(columns=cols)
        self._tree.heading("english", text="English (source)", anchor="w")
        self._tree.column("english", width=280, minwidth=160, stretch=False)
        for lang in self._non_en_languages():
            enabled = lang.get("enabled", True)
            heading = lang["name"] if enabled else f"{lang['name']} (off)"
            self._tree.heading(lang["code"], text=heading, anchor="w")
            self._tree.column(lang["code"], width=220, minwidth=120, stretch=True)

    def _refresh_table(self) -> None:
        self._tree.delete(*self._tree.get_children())
        strings: Dict[str, Any] = self._data.get("strings", {})
        langs = self._non_en_languages()
        missing = 0
        for english_text, translations in strings.items():
            values = [english_text] + [translations.get(l["code"], "") for l in langs]
            self._tree.insert("", "end", iid=english_text, values=values)
            for l in langs:
                if not translations.get(l["code"]):
                    missing += 1
        count = len(strings)
        self._status_label.configure(
            text=f"{count} string(s)  ·  {missing} missing translation(s)"
        )

    def _sync_and_refresh(self) -> None:
        self.sync_strings_from_config()
        self._on_dirty()

    # ------------------------------------------------------------------
    # Inline cell editing
    # ------------------------------------------------------------------

    def _on_table_click(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        item = self._tree.identify_row(event.y)
        col_id = self._tree.identify_column(event.x)
        if not item or not col_id:
            return
        # col_id is like "#1", "#2", ...
        col_num = int(col_id.lstrip("#")) - 1
        cols = list(self._tree.cget("columns"))
        if col_num < 0 or col_num >= len(cols):
            return
        values = list(self._tree.item(item, "values"))
        current = values[col_num] if col_num < len(values) else ""
        self._active_editor = _CellEditor(
            self._tree, item, col_id, current, self._on_cell_commit,
        )

    def _on_cell_commit(self, item: str, col_id: str, value: str) -> None:
        col_num = int(col_id.lstrip("#")) - 1
        cols = list(self._tree.cget("columns"))
        if col_num < 0 or col_num >= len(cols):
            return
        col_name = cols[col_num]
        new_value = value.strip()

        if col_name == "english":
            self._rename_english_string(item, new_value)
            return

        # Update in-memory data.
        strings = self._data.setdefault("strings", {})
        if item not in strings:
            strings[item] = {}
        if new_value:
            strings[item][col_name] = new_value
        else:
            strings[item].pop(col_name, None)

        # Update treeview cell.
        values = list(self._tree.item(item, "values"))
        if col_num < len(values):
            values[col_num] = new_value
        self._tree.item(item, values=values)
        self._update_status_count()
        self._on_dirty()

    def _rename_english_string(self, old: str, new: str) -> None:
        """Rename an English source string and propagate to all matching labels.

        Updates the key in self._data["strings"] (preserving order) and rewrites
        every label.text in the loaded config whose value matches `old`.
        """
        if not new or new == old:
            return
        strings = self._data.setdefault("strings", {})
        if new in strings:
            messagebox.showerror(
                "Rename English string",
                f"'{new}' already exists as a source string.",
                parent=self,
            )
            self._refresh_table()
            return

        self._data["strings"] = {
            (new if k == old else k): v for k, v in strings.items()
        }

        config = self._config_getter() or {}
        for brand_cfg in (config.get("brands") or {}).values():
            for shot in (brand_cfg.get("screenshots") or []):
                for label in (shot.get("labels") or []):
                    if str(label.get("text", "")) == old:
                        label["text"] = new

        self._refresh_table()
        self._on_dirty()
        if self._on_translation_change:
            self._on_translation_change()

    def _update_status_count(self) -> None:
        strings = self._data.get("strings", {})
        langs = self._non_en_languages()
        missing = sum(
            1 for t in strings.values() for l in langs if not t.get(l["code"])
        )
        self._status_label.configure(
            text=f"{len(strings)} string(s)  ·  {missing} missing translation(s)"
        )
