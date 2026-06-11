from __future__ import annotations

import contextlib
import io
import threading

import customtkinter as ctk

from core.versioning import get_local_version
from updates import github_updater
from updates.update_settings import CREATE_BACKUP, GITHUB_BRANCH, GITHUB_REPO, GITHUB_TOKEN, VERSION_FILE


class UpdatePanel:
    """Simple user-facing update panel. Creator settings live in update_settings.py."""

    def __init__(self, parent, scale_func=lambda value: int(value), version=None):
        self.parent = parent
        self.S = scale_func
        self.local_version = version or get_local_version()
        self.bg_card = "#1f1f1f"
        self.bg_soft = "#242424"
        self.bg_input = "#333333"
        self.accent = "#c0392b"
        self.accent_active = "#AA2A2A"
        self.accent_hover = "#BB3A3A"
        self.text_main = "#FFFFFF"
        self.text_muted = "#9A9A9A"
        self.border = "#333333"
        self._build()

    def _config(self):
        return {"github_update": {"repo": GITHUB_REPO, "branch": GITHUB_BRANCH or "main", "version_file": VERSION_FILE or "version", "token": GITHUB_TOKEN, "backup": bool(CREATE_BACKUP)}}

    def _status(self, text, color=None):
        self.parent.after(0, lambda: self.status_label.configure(text=text, text_color=color or self.text_muted))

    def _set_remote(self, text):
        self.parent.after(0, lambda: self.remote_value.configure(text=text))

    def _append_log(self, text):
        def apply():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", text.rstrip() + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.parent.after(0, apply)

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _stat_box(self, parent, col, title, value, color=None):
        box = ctk.CTkFrame(parent, fg_color=self.bg_soft, corner_radius=self.S(12))
        box.grid(row=0, column=col, sticky="ew", padx=self.S(8), pady=self.S(10))
        ctk.CTkLabel(box, text=title, text_color=self.text_muted, font=("Arial", self.S(11), "bold")).pack(pady=(self.S(10), self.S(2)))
        lbl = ctk.CTkLabel(box, text=value, text_color=color or self.text_main, font=("Arial", self.S(20), "bold"))
        lbl.pack(pady=(0, self.S(10)))
        return lbl

    def _build(self):
        root = ctk.CTkScrollableFrame(self.parent, fg_color="transparent", scrollbar_button_color=self.bg_input, scrollbar_button_hover_color=self.accent_hover)
        root.pack(expand=True, fill="both", padx=self.S(14), pady=self.S(10))
        root.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(root, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=self.S(8), pady=(self.S(4), self.S(10)))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Updates", text_color=self.text_main, font=("Arial", self.S(30), "bold"), anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="Check and install the latest Spectro build from the official GitHub source.", text_color=self.text_muted, font=("Arial", self.S(13)), anchor="w").grid(row=1, column=0, sticky="w", pady=(self.S(2), 0))

        summary = ctk.CTkFrame(root, fg_color=self.bg_card, corner_radius=self.S(14), border_width=1, border_color=self.border)
        summary.grid(row=1, column=0, sticky="ew", padx=self.S(8), pady=self.S(8))
        for col in range(3):
            summary.grid_columnconfigure(col, weight=1)
        self._stat_box(summary, 0, "Installed", self.local_version)
        self.remote_value = self._stat_box(summary, 1, "Latest", "Not checked", self.accent)
        self._stat_box(summary, 2, "Source", GITHUB_REPO if GITHUB_REPO else "Not configured")

        actions = ctk.CTkFrame(root, fg_color=self.bg_card, corner_radius=self.S(14), border_width=1, border_color=self.border)
        actions.grid(row=2, column=0, sticky="ew", padx=self.S(8), pady=self.S(8))
        actions.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(actions, text="Ready.", text_color=self.text_muted, font=("Arial", self.S(12)), anchor="w")
        self.status_label.grid(row=0, column=0, sticky="ew", padx=self.S(18), pady=self.S(18))
        ctk.CTkButton(actions, text="Check for Updates", command=self.check_update, fg_color=self.bg_input, hover_color=self.accent_hover, font=("Arial", self.S(14), "bold"), corner_radius=self.S(9), width=self.S(160), height=self.S(40)).grid(row=0, column=1, padx=(self.S(8), 0), pady=self.S(18))
        ctk.CTkButton(actions, text="Install Update", command=self.apply_update, fg_color=self.accent_active, hover_color=self.accent_hover, font=("Arial", self.S(14), "bold"), corner_radius=self.S(9), width=self.S(150), height=self.S(40)).grid(row=0, column=2, padx=self.S(18), pady=self.S(18))

        log_card = ctk.CTkFrame(root, fg_color=self.bg_card, corner_radius=self.S(14), border_width=1, border_color=self.border)
        log_card.grid(row=3, column=0, sticky="nsew", padx=self.S(8), pady=self.S(8))
        log_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(log_card, text="Update Log", text_color=self.text_main, font=("Arial", self.S(19), "bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=self.S(18), pady=(self.S(16), self.S(8)))
        self.log_box = ctk.CTkTextbox(log_card, height=self.S(310), fg_color=self.bg_soft, border_color=self.border, text_color=self.text_main, font=("Consolas", self.S(12)), wrap="word")
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=self.S(18), pady=(0, self.S(18)))
        self.log_box.configure(state="disabled")

    def _run_worker(self, action):
        self._clear_log()
        if not GITHUB_REPO or "/" not in GITHUB_REPO:
            self._status("Updater source is not configured by the creator.", "#E74C3C")
            self._append_log("Set GITHUB_REPO in updates/update_settings.py")
            return
        self._status("Working...", self.text_muted)

        def worker():
            buffer = io.StringIO()
            try:
                config = self._config()
                with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                    if action == "check":
                        local, remote, newer = github_updater.run_check(config)
                        print(f"Local version:  {local}")
                        print(f"Remote version: {remote}")
                        print("Update available." if newer else "Already up to date.")
                        self._set_remote(remote)
                    else:
                        github_updater.update_project(config, dry_run=False)
                self._append_log(buffer.getvalue() or "Done.")
                self._status("Done.", "#2ECC71")
            except BaseException as exc:
                output = buffer.getvalue()
                if output:
                    self._append_log(output)
                self._append_log(f"ERROR: {exc}")
                self._status("Failed. Check log.", "#E74C3C")

        threading.Thread(target=worker, daemon=True).start()

    def check_update(self):
        self._run_worker("check")

    def apply_update(self):
        self._run_worker("update")
