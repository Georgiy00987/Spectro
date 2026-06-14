import customtkinter as ctk
import asyncio
import subprocess
import sys
import threading
import webbrowser
import os
import json
import urllib.request
import urllib.error
import pyautogui
from pathlib import Path
from PIL import Image
import tkinter as tk
import re
from core.utils import (
    config_bool,
    load_toml_as_dict, save_dict_as_toml, get_discord_link, get_dpi_scale,
    save_brawler_data, load_brawler_data, normalize_brawler_name,
    load_brawl_stars_api_config, fetch_brawl_stars_player,
    fetch_brawl_stars_player_by_tag, save_brawler_icon,
    clear_toml_cache, get_config_player_tag
)
from core.window_icon import set_window_icon
from packaging import version
from core.performance_profile import (
    SCRCPY_CAPTURE_KEYS,
    SCRCPY_CAPTURE_PROFILES,
    apply_performance_profile,
    apply_scrcpy_capture_profile,
    detect_scrcpy_capture_profile,
)
from integrations.discord_notifier import async_send_test_notification
from updates.update_interface import UpdatePanel

orig_screen_width, orig_screen_height = 1920, 1080
width, height = pyautogui.size()
width_ratio = width / orig_screen_width
height_ratio = height / orig_screen_height
scale_factor = min(width_ratio, height_ratio)
scale_factor *= 96/get_dpi_scale()

def S(value):
    """Helper to scale integer sizes based on the user's screen."""
    return int(value * scale_factor)


class Hub:
    """
    Updated, more user-friendly interface for the Spectro bot.
    """

    def __init__(self,
                 version_str,
                 latest_version_str,
                 correct_zoom=True,
                 on_close_callback=None,
                 brawlers=None):

        self.version_str = version_str
        self.latest_version_str = latest_version_str
        self.correct_zoom = correct_zoom
        self.on_close_callback = on_close_callback
        self.start_requested = False
        self.closed_by_user = False
        self.brawlers = sorted(brawlers or [])
        self.queue_data = load_brawler_data()

        # -----------------------------------------------------------------------------------------
        # Load configs
        # -----------------------------------------------------------------------------------------
        self.bot_config_path = "cfg/bot_config.toml"
        self.time_tresholds_path = "cfg/time_tresholds.toml"
        self.match_history_path = "cfg/match_history.toml"
        self.general_config_path = "cfg/general_config.toml"
        self.webhook_config_path = "cfg/discord_config.toml"
        self.telegram_config_path = "cfg/telegram_config.toml"
        legacy_webhook_config_path = "cfg/webhook_config.toml"

        self.bot_config = load_toml_as_dict(self.bot_config_path)
        self.time_tresholds = load_toml_as_dict(self.time_tresholds_path)
        self.match_history = load_toml_as_dict(self.match_history_path)
        self.general_config = load_toml_as_dict(self.general_config_path)
        if not Path(self.webhook_config_path).exists() and Path(legacy_webhook_config_path).exists():
            self.webhook_config = load_toml_as_dict(legacy_webhook_config_path)
            save_dict_as_toml(self.webhook_config, self.webhook_config_path)
        else:
            self.webhook_config = load_toml_as_dict(self.webhook_config_path)
        self.telegram_config_root = load_toml_as_dict(self.telegram_config_path)
        if "telegram" not in self.telegram_config_root or not isinstance(self.telegram_config_root.get("telegram"), dict):
            self.telegram_config_root["telegram"] = {}
        self.telegram_config = self.telegram_config_root["telegram"]

        # -----------------------------------------------------------------------------------------
        # Defaults
        # -----------------------------------------------------------------------------------------
        # Bot config defaults
        self.bot_config.setdefault("gamemode_type", 3)
        self.bot_config.setdefault("gamemode", "brawlball")
        self.bot_config.setdefault("bot_uses_gadgets", "yes")
        self.bot_config.setdefault("minimum_movement_delay", 0.4)
        self.bot_config.setdefault("wall_detection_confidence", 0.9)
        self.bot_config.setdefault("entity_detection_confidence", 0.6)
        self.bot_config.setdefault("unstuck_movement_delay", 3.0)
        self.bot_config.setdefault("unstuck_movement_hold_time", 1.5)
        self.bot_config.setdefault("play_again_on_win", "no")
        self.bot_config.setdefault("aimed_attacks", "no")
        self.bot_config.setdefault("aimed_attack_radius", 320.0)
        self.bot_config.setdefault("aimed_attack_duration", 0.16)
        self.bot_config.setdefault("aimed_attack_end_hold", 0.08)
        self.bot_config.setdefault("aimed_attacks_ignore_imitation", "yes")
        self.bot_config.setdefault("imitation_enabled", "yes")
        self.bot_config.setdefault("current_playstyle", "default.pyla")


        # Time thresholds defaults
        self.time_tresholds.setdefault("state_check", 3)
        self.time_tresholds.setdefault("no_detections", 10)
        self.time_tresholds.setdefault("idle", 10)
        self.time_tresholds.setdefault("super", 0.1)
        self.time_tresholds.setdefault("gadget", 0.5)
        self.time_tresholds.setdefault("hypercharge", 2)

        # General config defaults
        self.general_config.setdefault("max_ips", "auto")
        self.general_config.setdefault("scrcpy_max_fps", 45)
        self.general_config.setdefault("scrcpy_max_width", 960)
        self.general_config.setdefault("scrcpy_bitrate", 2500000)
        self.general_config.setdefault("onnx_cpu_threads", "auto")
        self.general_config.setdefault("used_threads", self.general_config.get("onnx_cpu_threads", "auto"))
        self.general_config.setdefault("super_debug", "no")
        self.general_config.setdefault("cpu_or_gpu", "auto")
        self.general_config.setdefault("directml_device_id", "auto")
        self.general_config.setdefault("long_press_star_drop", "no")
        self.general_config.setdefault("trophies_multiplier", 1.0)
        self.general_config.setdefault("ocr_scale_down_factor", 0.5)
        self.general_config.setdefault("current_emulator", "LDPlayer")
        self.general_config.setdefault("emulator_port", 5555)
        self.general_config.setdefault("terminal_logging", "no")
        self.general_config.setdefault("visual_debug", "no")
        self.general_config.setdefault("visual_debug_scale", 0.6)
        self.general_config.setdefault("visual_debug_max_fps", 30)
        self.general_config.setdefault("visual_debug_max_boxes", 120)
        self.general_config.setdefault("capture_bad_vision_frames", "no")
        self.general_config.setdefault("developer", "no")

        self.webhook_config.setdefault("webhook_url", self.general_config.get("personal_webhook", ""))
        self.webhook_config.setdefault("discord_id", self.general_config.get("discord_id", ""))
        self.webhook_config.setdefault("username", "Spectro")
        self.webhook_config.setdefault("send_match_summary", False)
        self.webhook_config.setdefault("include_screenshot", True)
        self.webhook_config.setdefault("ping_when_stuck", False)
        self.webhook_config.setdefault("ping_when_target_is_reached", False)
        self.webhook_config.setdefault("ping_every_x_match", 0)
        self.webhook_config.setdefault("ping_every_x_minutes", 0)
        self.webhook_config.setdefault("discord_control_enabled", False)
        self.webhook_config.setdefault("discord_bot_token", "")
        self.webhook_config.setdefault("discord_control_user_id", "")
        self.webhook_config.setdefault("discord_control_channel_id", "")
        self.webhook_config.setdefault("discord_control_guild_id", "")

        self.telegram_config.setdefault("enabled", False)
        self.telegram_config.setdefault("bot_token", "YOUR_BOT_TOKEN")
        self.telegram_config.setdefault("chat_id", "YOUR_CHAT_ID")
        self.telegram_config.setdefault("poll_timeout", 20)
        self.telegram_config.setdefault("idle_sleep", 8)

        # -----------------------------------------------------------------------------------------
        # Appearance
        # -----------------------------------------------------------------------------------------
        ctk.set_appearance_mode("dark")

        # For showing tooltips in Toplevel windows
        # For showing tooltips
        self.tooltip_window = None
        self._tooltip_after_id = None
        self._tooltip_owner = None
        self._tooltip_text = ""

        # -----------------------------------------------------------------------------------------
        # Main window
        # -----------------------------------------------------------------------------------------
        self.app = ctk.CTk()
        self.app.title(f"Spectro Hub - {self.version_str}")
        self.app.geometry(f"{S(1000)}x{S(750)}")
        self.app.resizable(False, False)
        set_window_icon(self.app)
        self.app.protocol("WM_DELETE_WINDOW", self._on_close)

        # Hide tooltip on "global" interactions (tab switch, clicks, scroll, key press, focus loss, etc.)
        for seq in ("<ButtonPress>", "<MouseWheel>", "<KeyPress>", "<FocusOut>"):
            self.app.bind_all(seq, self._hide_tooltip, add="+")
        self.app.bind("<Configure>", self._hide_tooltip, add="+")  # window move/resize

        # -----------------------------------------------------------------------------------------
        # Main TabView
        # -----------------------------------------------------------------------------------------
        self.tabview = ctk.CTkTabview(
            self.app,
            width=S(980),
            height=S(730),
            corner_radius=S(10)
        )
        self.tabview.pack(pady=S(10), padx=S(10), fill="x", expand=False)

        # Enlarge the segmented tab buttons
        self.tabview._segmented_button.configure(
            corner_radius=S(10),
            border_width=2,
            fg_color="#4A4A4A",
            selected_color="#AA2A2A",
            selected_hover_color="#BB3A3A",
            unselected_color="#333333",
            unselected_hover_color="#555555",
            text_color="#FFFFFF",
            font=("Arial", S(16), "bold"),
            height=S(40)
        )

        # Add tabs
        self.tab_overview = self.tabview.add("Overview")
        self.tab_queue = self.tabview.add("Brawler Queue")
        self.tab_additional = self.tabview.add("Additional Settings")
        self.tab_webhook = self.tabview.add("Integrations")
        self.tab_updates = self.tabview.add("Updates")
        self.developer_enabled = config_bool(self.general_config.get("developer"), False)
        if self.developer_enabled:
            self.tab_developer = self.tabview.add("Developer")
        self.tab_timers = self.tabview.add("Timers")
        self.tab_history = self.tabview.add("Match History")

        # Init each tab
        self._init_overview_tab()
        self._init_brawler_queue_tab()
        self._init_additional_tab()
        self._init_webhook_tab()
        self._init_updates_tab()
        if self.developer_enabled:
            self._init_developer_tab()
        self._init_timers_tab()
        self._init_history_tab()

        # Main loop
        self.app.mainloop()

    # ---------------------------------------------------------------------------------------------
    #  Tooltip Handler
    # ---------------------------------------------------------------------------------------------
    def _pointer_over_widget(self, widget) -> bool:
        if widget is None or not widget.winfo_exists():
            return False
        try:
            px, py = widget.winfo_pointerx(), widget.winfo_pointery()
            x, y = widget.winfo_rootx(), widget.winfo_rooty()
            w, h = widget.winfo_width(), widget.winfo_height()
            return x <= px <= x + w and y <= py <= y + h
        except tk.TclError:
            return False

    def _hide_tooltip(self, _event=None):
        # cancel delayed show if pending
        if self._tooltip_after_id is not None:
            try:
                self.app.after_cancel(self._tooltip_after_id)
            except Exception:
                pass
            self._tooltip_after_id = None

        # destroy current tooltip window
        if self.tooltip_window is not None:
            try:
                self.tooltip_window.destroy()
            except Exception:
                pass
            self.tooltip_window = None

        self._tooltip_owner = None
        self._tooltip_text = ""

    def attach_tooltip(self, widget, text, delay_ms: int = 250):
        """
        Robust tooltip:
        - shows after delay
        - hides on Leave, Unmap (tab switch), Destroy, clicks/scroll/keys (via global binds)
        - prevents stuck tooltips when switching tabs
        """

        def schedule_show(event=None):
            # reset any existing tooltip
            self._hide_tooltip()

            self._tooltip_owner = widget
            self._tooltip_text = text

            def do_show():
                # widget may have disappeared / tab switched
                if (self._tooltip_owner is None
                        or not self._tooltip_owner.winfo_exists()
                        or not self._tooltip_owner.winfo_viewable()
                        or not self._pointer_over_widget(self._tooltip_owner)):
                    self._hide_tooltip()
                    return

                # create tooltip
                self.tooltip_window = ctk.CTkToplevel(self.app)
                self.tooltip_window.overrideredirect(True)
                self.tooltip_window.attributes("-topmost", True)

                # position near cursor
                px = self.app.winfo_pointerx()
                py = self.app.winfo_pointery()
                self.tooltip_window.geometry(f"+{px + 12}+{py + 12}")

                label = ctk.CTkLabel(
                    self.tooltip_window,
                    text=self._tooltip_text,
                    fg_color="#333333",
                    text_color="#FFFFFF",
                    corner_radius=S(6),
                    font=("Arial", S(12))
                )
                label.pack(padx=S(6), pady=S(4))

                # if mouse enters tooltip itself, hide (avoids "stuck" hovering on tooltip)
                self.tooltip_window.bind("<Enter>", self._hide_tooltip)
                self.tooltip_window.bind("<Leave>", self._hide_tooltip)

            self._tooltip_after_id = self.app.after(delay_ms, do_show)

        def on_leave(_event=None):
            self._hide_tooltip()

        # Bindings
        widget.bind("<Enter>", schedule_show, add="+")
        widget.bind("<Leave>", on_leave, add="+")
        widget.bind("<Unmap>", on_leave, add="+")  # IMPORTANT: tab switching / frame hidden
        widget.bind("<Destroy>", on_leave, add="+")  # safety
        widget.bind("<ButtonPress>", on_leave, add="+")  # click on the widget -> hide

    # ---------------------------------------------------------------------------------------------
    #  Overview Tab
    # ---------------------------------------------------------------------------------------------
    def _init_overview_tab(self):
        frame = self.tab_overview

        bg_card = "#1f1f1f"
        bg_soft = "#242424"
        bg_input = "#333333"
        accent = "#c0392b"
        accent_hover = "#BB3A3A"
        text_main = "#FFFFFF"
        text_muted = "#9A9A9A"
        border = "#333333"

        root = ctk.CTkScrollableFrame(
            frame,
            fg_color="transparent",
            scrollbar_button_color=bg_input,
            scrollbar_button_hover_color=accent_hover,
        )
        root.pack(expand=True, fill="both", padx=S(14), pady=S(10))
        root.grid_columnconfigure(0, weight=1)
        root.grid_columnconfigure(1, weight=1)

        def make_card(row, column, title, subtitle, columnspan=1):
            card = ctk.CTkFrame(root, fg_color=bg_card, corner_radius=S(14), border_width=1, border_color=border)
            card.grid(row=row, column=column, columnspan=columnspan, sticky="nsew", padx=S(8), pady=S(8))
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=title, text_color=text_main, font=("Arial", S(20), "bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=S(18), pady=(S(18), S(2)))
            ctk.CTkLabel(card, text=subtitle, text_color=text_muted, font=("Arial", S(12)), anchor="w", justify="left", wraplength=S(820 if columnspan == 2 else 360)).grid(row=1, column=0, sticky="ew", padx=S(18), pady=(0, S(14)))
            return card, 2

        def label(parent, row, text):
            ctk.CTkLabel(parent, text=text, text_color=text_muted, font=("Arial", S(12), "bold"), anchor="w").grid(row=row, column=0, sticky="w", padx=S(18), pady=(S(4), S(6)))

        def option(parent, row, var, values, command, width=300):
            menu = ctk.CTkOptionMenu(
                parent,
                variable=var,
                values=values,
                command=command,
                width=S(width),
                height=S(40),
                fg_color=bg_input,
                button_color=accent,
                button_hover_color=accent_hover,
                dropdown_fg_color=bg_card,
                dropdown_hover_color=accent,
                dropdown_text_color=text_main,
                text_color=text_main,
                font=("Arial", S(14), "bold"),
                dropdown_font=("Arial", S(13)),
                corner_radius=S(9),
            )
            menu.grid(row=row, column=0, sticky="w", padx=S(18), pady=(0, S(12)))
            return menu

        header = ctk.CTkFrame(root, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=S(8), pady=(S(4), S(10)))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Overview", text_color=text_main, font=("Arial", S(31), "bold"), anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text=f"Spectro v{self.version_str}. Choose the essentials and start.", text_color=text_muted, font=("Arial", S(13)), anchor="w").grid(row=1, column=0, sticky="w", pady=(S(2), 0))

        warnings = []
        if not self.correct_zoom:
            warnings.append("Windows zoom is not 100%. Set DPI to 96 for best accuracy.")
        try:
            if self.latest_version_str and version.parse(self.version_str) < version.parse(self.latest_version_str):
                warnings.append(f"Update available: {self.latest_version_str}")
        except Exception:
            pass
        if warnings:
            warn_box = ctk.CTkFrame(header, fg_color="#2a1717", corner_radius=S(10), border_width=1, border_color=accent)
            warn_box.grid(row=0, column=1, rowspan=2, sticky="e", padx=(S(12), 0))
            ctk.CTkLabel(warn_box, text="\n".join(warnings), text_color="#e74c3c", font=("Arial", S(12), "bold"), justify="left").pack(padx=S(12), pady=S(8))

        gameplay, row = make_card(1, 0, "Gameplay", "Mode selection is compact, clean and easy to extend later.")
        mode_profiles = [
            {"title": "Brawlball", "value": "brawlball", "orientation": 3, "description": "Vertical maps"},
            {"title": "Other", "value": "other", "orientation": 3, "description": "Generic vertical preset"},
            {"title": "Basket Brawl", "value": "basketbrawl", "orientation": 5, "description": "Horizontal maps"},
            {"title": "Brawlball 5v5", "value": "brawlball_5v5", "orientation": 5, "description": "Horizontal 5v5 preset"},
            {"title": "Showdown Trio", "value": "showdown", "orientation": 3, "description": "Coming soon", "disabled": True},
        ]
        mode_by_title = {item["title"]: item for item in mode_profiles}
        mode_by_value = {item["value"]: item for item in mode_profiles}
        current_mode_profile = mode_by_value.get(self.bot_config.get("gamemode", "brawlball"), mode_profiles[0])
        if current_mode_profile.get("disabled"):
            current_mode_profile = mode_profiles[0]
        self.gamemode_type_var = tk.IntVar(value=current_mode_profile["orientation"])
        self.gamemode_var = tk.StringVar(value=current_mode_profile["value"])
        self.overview_mode_var = tk.StringVar(value=current_mode_profile["title"])

        label(gameplay, row, "Mode")
        row += 1
        def update_mode_summary(profile):
            orientation_name = "Vertical" if profile["orientation"] == 3 else "Horizontal"
            self.overview_gm_summary.configure(text=f"{profile['description']}  •  Orientation: {orientation_name}")
        def handle_mode_choice(choice):
            profile = mode_by_title.get(choice, mode_profiles[0])
            if profile.get("disabled"):
                return
            self.bot_config["gamemode_type"] = profile["orientation"]
            self.bot_config["gamemode"] = profile["value"]
            save_dict_as_toml(self.bot_config, self.bot_config_path)
            self.gamemode_type_var.set(profile["orientation"])
            self.gamemode_var.set(profile["value"])
            self.overview_mode_var.set(profile["title"])
            update_mode_summary(profile)
        option(gameplay, row, self.overview_mode_var, [m["title"] for m in mode_profiles if not m.get("disabled")], handle_mode_choice)
        row += 1
        summary = ctk.CTkFrame(gameplay, fg_color=bg_soft, corner_radius=S(10))
        summary.grid(row=row, column=0, sticky="ew", padx=S(18), pady=(S(2), S(16)))
        self.overview_gm_summary = ctk.CTkLabel(summary, text="", text_color=text_muted, font=("Arial", S(12)), anchor="w")
        self.overview_gm_summary.pack(fill="x", padx=S(12), pady=S(9))
        update_mode_summary(current_mode_profile)
        self._refresh_orientation_buttons = lambda: None
        self._refresh_gamemode_buttons = lambda: update_mode_summary(mode_by_value.get(self.gamemode_var.get(), mode_profiles[0]))

        device, row = make_card(1, 1, "Device", "Choose emulator profile and optionally set your Brawl Stars tag.")
        emulator_profiles = [
            {"title": "LDPlayer", "port": 5555},
            {"title": "MuMu", "port": 16384},
            {"title": "BlueStacks", "port": 5555},
            {"title": "Nox", "port": 62001},
            {"title": "MEmu", "port": 21503},
            {"title": "GameLoop", "port": 5555},
        ]
        emu_by_title = {item["title"]: item for item in emulator_profiles}
        supported_emulators = {item["title"]: item["port"] for item in emulator_profiles}
        current_emulator = self.general_config.get("current_emulator", "LDPlayer")
        if current_emulator not in supported_emulators:
            current_emulator = "LDPlayer"
        self.emu_var = tk.StringVar(value=current_emulator)
        label(device, row, "Emulator")
        row += 1
        def update_emu_summary(choice):
            self.overview_emu_summary.configure(text=f"Selected emulator: {choice}")
        def handle_emulator_choice(choice):
            profile = emu_by_title.get(choice, emulator_profiles[0])
            self.emu_var.set(profile["title"])
            self.general_config["current_emulator"] = profile["title"]
            self.general_config["emulator_port"] = profile["port"]
            save_dict_as_toml(self.general_config, self.general_config_path)
            update_emu_summary(profile["title"])
        option(device, row, self.emu_var, [item["title"] for item in emulator_profiles], handle_emulator_choice)
        row += 1
        label(device, row, "Game ID")
        row += 1
        self.brawl_stars_api_path = "cfg/brawl_stars_api.toml"
        try:
            api_config = dict(load_toml_as_dict(self.brawl_stars_api_path))
            loaded_tag = get_config_player_tag(api_config).strip()
        except Exception:
            loaded_tag = ""
        if loaded_tag.upper() == "#YOURTAG":
            loaded_tag = ""
        self.player_tag_var = tk.StringVar(value=loaded_tag)
        def save_player_tag(*_):
            new_tag = self.player_tag_var.get().strip()
            if new_tag and not new_tag.startswith("#"):
                new_tag = f"#{new_tag}"
            self.player_tag_var.set(new_tag)
            stored_tag = new_tag if new_tag else "#YOURTAG"
            try:
                text = Path(self.brawl_stars_api_path).read_text(encoding="utf-8-sig")
            except FileNotFoundError:
                text = ""
            escaped = stored_tag.replace("\\", "\\\\").replace('"', '\\"')
            if re.search(r'(?m)^[ \t]*player_tag[ \t]*=.*', text):
                text = re.sub(r'(?m)^[ \t]*player_tag[ \t]*=.*', 'player_tag = "' + escaped + '"', text, count=1)
            else:
                if text and not text.endswith("\n"):
                    text += "\n"
                text += 'player_tag = "' + escaped + '"\n'
            Path(self.brawl_stars_api_path).write_text(text, encoding="utf-8")
            clear_toml_cache(self.brawl_stars_api_path)
        entry = ctk.CTkEntry(device, textvariable=self.player_tag_var, width=S(300), height=S(40), fg_color=bg_soft, border_color=border, text_color=text_main, placeholder_text="#PLAYER TAG", font=("Arial", S(14)))
        entry.grid(row=row, column=0, sticky="w", padx=S(18), pady=(0, S(12)))
        entry.bind("<FocusOut>", save_player_tag)
        entry.bind("<Return>", save_player_tag)
        row += 1
        emu_summary = ctk.CTkFrame(device, fg_color=bg_soft, corner_radius=S(10))
        emu_summary.grid(row=row, column=0, sticky="ew", padx=S(18), pady=(S(2), S(16)))
        self.overview_emu_summary = ctk.CTkLabel(emu_summary, text="", text_color=text_muted, font=("Arial", S(12)), anchor="w")
        self.overview_emu_summary.pack(fill="x", padx=S(12), pady=S(9))
        update_emu_summary(current_emulator)

        ready, row = make_card(2, 0, "Ready", "Start the bot with the selected setup.", columnspan=2)
        ready.grid_columnconfigure(0, weight=1)
        ready.grid_columnconfigure(1, weight=0)
        ctk.CTkLabel(ready, text="Make sure the emulator is open, Brawl Stars is visible, and your queue is configured.", text_color=text_muted, font=("Arial", S(12)), anchor="w", justify="left", wraplength=S(620)).grid(row=row, column=0, sticky="ew", padx=S(18), pady=(0, S(16)))
        ctk.CTkButton(ready, text="Start", fg_color=accent, hover_color="#e74c3c", text_color=text_main, font=("Arial", S(23), "bold"), command=self._on_start, corner_radius=S(12), width=S(210), height=S(58)).grid(row=0, column=1, rowspan=3, sticky="e", padx=S(18), pady=S(16))

        info, row = make_card(3, 0, "Information", "Short guide and overview of the program.", columnspan=2)
        info_text = (
            "Spectro is an automation assistant for Brawl Stars. It is designed to run through an Android emulator, "
            "read the current game state from the screen, detect important objects, and control movement and actions through the configured key layout.\n\n"
            "Main workflow: choose an emulator, select a game mode, configure a brawler or queue, then press Start. "
            "During a match Spectro tracks the player, enemies, walls, ball position, abilities, match result, trophies, and recovery states.\n\n"
            "Brawler Queue lets you prepare multiple brawlers with trophy or win targets. Push All can build a queue from opened brawlers that are below the selected target, so already completed brawlers are skipped.\n\n"
            "Additional Settings contains performance, behavior, vision and debug options. Use performance profiles when you want a quick safe preset, and only tune detection thresholds if the bot starts missing walls, players, abilities or OCR.\n\n"
            "Integrations contains remote control and notifications. Telegram control can pause, resume, stop and show status while the bot is running. Discord can send match summaries and alerts.\n\n"
            "Timers control how often the bot checks combat actions and recovery states. Lower values can react faster but may use more resources. Higher values are calmer and lighter for weaker PCs.\n\n"
            "Match History stores basic results by brawler, including wins, losses, draws and win rate. This is useful for checking which brawlers or settings are performing better.\n\n"
            "Contacts: Telegram @frendls, Telegram channel @forget_git.\n\n"
            "Recommended setup: Windows 64-bit, Python 3.11, a supported Android emulator such as LDPlayer, MuMu, BlueStacks, Nox, MEmu or GameLoop, emulator resolution 1920x1080, Windows scaling at 100%, and Brawl Stars visible in the foreground before starting.\n\n"
            "Useful config files: cfg/general_config.toml for emulator and performance, cfg/bot_config.toml for gameplay behavior, "
            "cfg/brawler_pick.toml for queue data, cfg/time_tresholds.toml for timer values, cfg/telegram_config.toml and cfg/discord_config.toml for integrations, "
            "and cfg/brawl_stars_api.toml for trophy autofill."
        )
        ctk.CTkLabel(info, text=info_text, text_color=text_muted, font=("Arial", S(12)), anchor="w", justify="left", wraplength=S(860)).grid(row=row, column=0, sticky="ew", padx=S(18), pady=(0, S(18)))

    def _init_brawler_queue_tab(self):
        frame = self.tab_queue

        self.queue_bg_card = "#1f1f1f"
        self.queue_bg_soft = "#242424"
        self.queue_bg_input = "#333333"
        self.queue_accent = "#c0392b"
        self.queue_accent_active = "#AA2A2A"
        self.queue_accent_hover = "#BB3A3A"
        self.queue_text_main = "#FFFFFF"
        self.queue_text_muted = "#9A9A9A"
        self.queue_border = "#333333"

        container = ctk.CTkFrame(frame, fg_color="transparent")
        container.pack(expand=True, fill="both", padx=S(14), pady=S(10))
        container.grid_columnconfigure(0, weight=3)
        container.grid_columnconfigure(1, weight=2)
        container.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(container, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=S(8), pady=(S(4), S(10)))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Brawler Queue",
            text_color=self.queue_text_main,
            font=("Arial", S(30), "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Pick brawlers, set targets, then let Spectro switch to the next one automatically.",
            text_color=self.queue_text_muted,
            font=("Arial", S(13)),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(S(2), 0))

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        ctk.CTkButton(
            actions,
            text="Push All",
            width=S(120),
            height=S(36),
            fg_color=self.queue_accent_active,
            hover_color=self.queue_accent_hover,
            font=("Arial", S(13), "bold"),
            corner_radius=S(9),
            command=self._queue_push_all,
        ).pack(side="left", padx=(0, S(8)))
        ctk.CTkButton(
            actions,
            text="Clear",
            width=S(92),
            height=S(36),
            fg_color=self.queue_bg_input,
            hover_color=self.queue_accent_hover,
            font=("Arial", S(13), "bold"),
            corner_radius=S(9),
            command=self._queue_clear,
        ).pack(side="left")

        library_card = ctk.CTkFrame(
            container,
            fg_color=self.queue_bg_card,
            corner_radius=S(14),
            border_width=S(1),
            border_color=self.queue_border,
        )
        library_card.grid(row=1, column=0, sticky="nsew", padx=S(8), pady=S(8))
        library_card.grid_columnconfigure(0, weight=1)
        library_card.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            library_card,
            text="Brawler Library",
            text_color=self.queue_text_main,
            font=("Arial", S(19), "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=S(18), pady=(S(16), S(2)))
        ctk.CTkLabel(
            library_card,
            text="Search and click an icon to add or update a queue target.",
            text_color=self.queue_text_muted,
            font=("Arial", S(12)),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=S(18), pady=(0, S(12)))

        search_row = ctk.CTkFrame(library_card, fg_color="transparent")
        search_row.grid(row=2, column=0, sticky="ew", padx=S(18), pady=(0, S(10)))
        search_row.grid_columnconfigure(0, weight=1)

        self.queue_filter_var = tk.StringVar()
        search_entry = ctk.CTkEntry(
            search_row,
            textvariable=self.queue_filter_var,
            height=S(38),
            fg_color=self.queue_bg_soft,
            border_color=self.queue_border,
            text_color=self.queue_text_main,
            placeholder_text="Search brawler...",
            font=("Arial", S(14)),
        )
        search_entry.grid(row=0, column=0, sticky="ew")
        self.queue_filter_var.trace_add(
            "write", lambda *a: self._queue_render_icons(self.queue_filter_var.get()))

        if not hasattr(self, "queue_images"):
            self.queue_images = []
            for brawler in self.brawlers:
                img_path = f"./api/assets/brawler_icons/{brawler}.png"
                try:
                    img = Image.open(img_path)
                except FileNotFoundError:
                    try:
                        save_brawler_icon(brawler)
                        img = Image.open(img_path)
                    except Exception:
                        continue
                self.queue_images.append((brawler, ctk.CTkImage(img, size=(S(58), S(58)))))

        self.queue_icon_frame = ctk.CTkScrollableFrame(
            library_card,
            fg_color="transparent",
            width=S(560),
            height=S(430),
            scrollbar_button_color=self.queue_bg_input,
            scrollbar_button_hover_color=self.queue_accent_hover,
        )
        self.queue_icon_frame.grid(row=3, column=0, sticky="nsew", padx=S(14), pady=(0, S(16)))
        for col in range(6):
            self.queue_icon_frame.grid_columnconfigure(col, weight=1)

        queue_card = ctk.CTkFrame(
            container,
            fg_color=self.queue_bg_card,
            corner_radius=S(14),
            border_width=S(1),
            border_color=self.queue_border,
        )
        queue_card.grid(row=1, column=1, sticky="nsew", padx=S(8), pady=S(8))
        queue_card.grid_columnconfigure(0, weight=1)
        queue_card.grid_rowconfigure(3, weight=1)

        queue_head = ctk.CTkFrame(queue_card, fg_color="transparent")
        queue_head.grid(row=0, column=0, sticky="ew", padx=S(18), pady=(S(16), S(2)))
        queue_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            queue_head,
            text="Current Queue",
            text_color=self.queue_text_main,
            font=("Arial", S(19), "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.queue_count_label = ctk.CTkLabel(
            queue_head,
            text="0 items",
            text_color=self.queue_accent,
            font=("Arial", S(12), "bold"),
        )
        self.queue_count_label.grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(
            queue_card,
            text="Use arrows to reorder. The first brawler is handled first.",
            text_color=self.queue_text_muted,
            font=("Arial", S(12)),
            anchor="w",
            wraplength=S(330),
        ).grid(row=1, column=0, sticky="ew", padx=S(18), pady=(0, S(12)))

        self.queue_status_label = ctk.CTkLabel(
            queue_card,
            text="",
            font=("Arial", S(12)),
            text_color=self.queue_text_muted,
            anchor="w",
            justify="left",
            wraplength=S(330),
        )
        self.queue_status_label.grid(row=2, column=0, sticky="ew", padx=S(18), pady=(0, S(8)))

        self.queue_list_frame = ctk.CTkScrollableFrame(
            queue_card,
            fg_color="transparent",
            width=S(340),
            height=S(420),
            scrollbar_button_color=self.queue_bg_input,
            scrollbar_button_hover_color=self.queue_accent_hover,
        )
        self.queue_list_frame.grid(row=3, column=0, sticky="nsew", padx=S(14), pady=(0, S(16)))
        self.queue_list_frame.grid_columnconfigure(0, weight=1)

        self._queue_render_icons("")
        self._refresh_queue_list()

    def _queue_render_icons(self, filter_text=""):
        filter_text = (filter_text or "").strip().lower()
        for widget in self.queue_icon_frame.winfo_children():
            widget.destroy()

        matches = [(b, img) for b, img in self.queue_images if filter_text in b.lower()]
        if not matches:
            ctk.CTkLabel(
                self.queue_icon_frame,
                text="No brawlers found.",
                font=("Arial", S(14)),
                text_color=getattr(self, "queue_text_muted", "#9A9A9A"),
            ).grid(row=0, column=0, sticky="w", padx=S(8), pady=S(8))
            return

        for index, (brawler, img_tk) in enumerate(matches):
            row_num, col_num = divmod(index, 6)
            tile = ctk.CTkFrame(
                self.queue_icon_frame,
                fg_color=getattr(self, "queue_bg_soft", "#242424"),
                corner_radius=S(10),
                border_width=S(1),
                border_color=getattr(self, "queue_border", "#333333"),
            )
            tile.grid(row=row_num, column=col_num, padx=S(5), pady=S(5), sticky="nsew")
            tile.grid_columnconfigure(0, weight=1)

            icon = ctk.CTkLabel(tile, image=img_tk, text="")
            icon._spectro_image_ref = img_tk
            icon.grid(row=0, column=0, padx=S(7), pady=(S(7), S(2)))

            display_name = str(brawler).replace("_", " ").title()
            name = ctk.CTkLabel(
                tile,
                text=display_name,
                font=("Arial", S(10), "bold"),
                text_color=getattr(self, "queue_text_muted", "#9A9A9A"),
                width=S(74),
            )
            name.grid(row=1, column=0, padx=S(4), pady=(0, S(7)))

            for widget in (tile, icon, name):
                widget.bind("<Button-1>", lambda _e, b=brawler: self._queue_open_entry(b), add="+")

    def _queue_open_entry(self, brawler):
        top = ctk.CTkToplevel(self.app)
        top.title("Add Brawler")
        top.geometry(f"{S(360)}x{S(340)}")
        top.attributes("-topmost", True)
        top.configure(fg_color="#141414")

        card = ctk.CTkFrame(
            top,
            fg_color=getattr(self, "queue_bg_card", "#1f1f1f"),
            corner_radius=S(14),
            border_width=S(1),
            border_color=getattr(self, "queue_border", "#333333"),
        )
        card.pack(expand=True, fill="both", padx=S(14), pady=S(14))
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=str(brawler).replace("_", " ").title(),
            font=("Arial", S(22), "bold"),
            text_color=getattr(self, "queue_text_main", "#FFFFFF"),
        ).grid(row=0, column=0, sticky="w", padx=S(18), pady=(S(18), S(2)))
        ctk.CTkLabel(
            card,
            text="Set target and add this brawler to queue.",
            font=("Arial", S(12)),
            text_color=getattr(self, "queue_text_muted", "#9A9A9A"),
        ).grid(row=1, column=0, sticky="w", padx=S(18), pady=(0, S(14)))

        type_var = tk.StringVar(value="trophies")
        ctk.CTkLabel(card, text="Target type", text_color=getattr(self, "queue_text_muted", "#9A9A9A"), font=("Arial", S(12), "bold")).grid(row=2, column=0, sticky="w", padx=S(18), pady=(0, S(6)))
        ctk.CTkOptionMenu(
            card,
            values=["trophies", "wins"],
            variable=type_var,
            width=S(220),
            height=S(38),
            fg_color=getattr(self, "queue_bg_input", "#333333"),
            button_color=getattr(self, "queue_accent_active", "#AA2A2A"),
            button_hover_color=getattr(self, "queue_accent_hover", "#BB3A3A"),
        ).grid(row=3, column=0, sticky="w", padx=S(18), pady=(0, S(12)))

        target_var = tk.StringVar(value="1000")
        ctk.CTkLabel(card, text="Target", text_color=getattr(self, "queue_text_muted", "#9A9A9A"), font=("Arial", S(12), "bold")).grid(row=4, column=0, sticky="w", padx=S(18), pady=(0, S(6)))
        ctk.CTkEntry(
            card,
            textvariable=target_var,
            width=S(220),
            height=S(38),
            fg_color=getattr(self, "queue_bg_soft", "#242424"),
            border_color=getattr(self, "queue_border", "#333333"),
            text_color=getattr(self, "queue_text_main", "#FFFFFF"),
            font=("Arial", S(14)),
        ).grid(row=5, column=0, sticky="w", padx=S(18), pady=(0, S(12)))

        auto_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            card,
            text="Auto-pick this brawler",
            variable=auto_var,
            fg_color=getattr(self, "queue_accent_active", "#AA2A2A"),
            hover_color=getattr(self, "queue_accent_hover", "#BB3A3A"),
            text_color=getattr(self, "queue_text_muted", "#9A9A9A"),
        ).grid(row=6, column=0, sticky="w", padx=S(18), pady=(0, S(14)))

        def submit():
            try:
                target = int(float(target_var.get()))
            except (TypeError, ValueError):
                self._set_queue_status("Target must be a number.")
                return
            ptype = type_var.get() if type_var.get() in ("trophies", "wins") else "trophies"
            row = self._queue_row_template(brawler, target, ptype)
            row["automatically_pick"] = bool(auto_var.get())
            self.queue_data = [
                r for r in self.queue_data
                if normalize_brawler_name(r.get("brawler", "")) != normalize_brawler_name(brawler)
            ]
            self.queue_data.append(row)
            self._save_queue()
            self._set_queue_status(f"Added: {brawler} -> {target} ({ptype}).")
            top.destroy()

        ctk.CTkButton(
            card,
            text="Add to Queue",
            fg_color=getattr(self, "queue_accent", "#c0392b"),
            hover_color=getattr(self, "queue_accent_hover", "#BB3A3A"),
            font=("Arial", S(15), "bold"),
            corner_radius=S(9),
            width=S(220),
            height=S(40),
            command=submit,
        ).grid(row=7, column=0, sticky="w", padx=S(18), pady=(0, S(18)))

    def _queue_row_template(self, brawler, target, ptype):
        return {
            "brawler": brawler, "push_until": int(target), "trophies": 0, "wins": 0,
            "type": ptype, "automatically_pick": True, "selection_method": "manual", "win_streak": 0,
        }

    def _queue_add_brawler(self):
        brawler = (self.queue_brawler_var.get() or "").strip()
        if not brawler:
            self._set_queue_status("Выбери бойца.");
            return
        try:
            target = int(float(self.queue_target_var.get()))
        except (TypeError, ValueError):
            self._set_queue_status("Цель должна быть числом.");
            return
        ptype = self.queue_type_var.get() if self.queue_type_var.get() in ("trophies", "wins") else "trophies"
        for row in self.queue_data:
            if normalize_brawler_name(row.get("brawler", "")) == normalize_brawler_name(brawler):
                row["push_until"] = target;
                row["type"] = ptype;
                row["selection_method"] = "manual"
                self._save_queue();
                self._set_queue_status(f"Обновлено: {brawler} → {target} ({ptype}).");
                return
        self.queue_data.append(self._queue_row_template(brawler, target, ptype))
        self._save_queue();
        self._set_queue_status(f"Добавлено: {brawler} → {target} ({ptype}).")

    def _queue_clear(self):
        self.queue_data = [];
        self._save_queue();
        self._set_queue_status("Очередь очищена.")

    def _queue_remove(self, index):
        if 0 <= index < len(self.queue_data):
            removed = self.queue_data.pop(index)
            self._save_queue();
            self._set_queue_status(f"Удалён: {removed.get('brawler', '')}.")

    def _queue_move(self, index, delta):
        new_index = index + delta
        if 0 <= index < len(self.queue_data) and 0 <= new_index < len(self.queue_data):
            self.queue_data[index], self.queue_data[new_index] = self.queue_data[new_index], self.queue_data[index]
            self._save_queue()

    def _save_queue(self):
        for index, row in enumerate(self.queue_data):
            row.setdefault("trophies", 0);
            row.setdefault("wins", 0)
            row.setdefault("win_streak", 0);
            row.setdefault("selection_method", "manual")
            if row.get("selection_method") == "lowest_trophies":
                row["automatically_pick"] = index != 0  # родная семантика Push All
            else:
                row.setdefault("automatically_pick", True)  # сохраняем выбор из окна
        save_brawler_data(self.queue_data)
        self._refresh_queue_list()

    def _set_queue_status(self, text):
        try:
            self.queue_status_label.configure(text=text)
        except Exception:
            pass

    def _refresh_queue_list(self):
        for child in self.queue_list_frame.winfo_children():
            child.destroy()

        if hasattr(self, "queue_count_label"):
            count = len(self.queue_data)
            self.queue_count_label.configure(text=f"{count} item" + ("" if count == 1 else "s"))

        if not self.queue_data:
            empty = ctk.CTkFrame(
                self.queue_list_frame,
                fg_color=getattr(self, "queue_bg_card", "#1f1f1f"),
                corner_radius=S(12),
                border_width=S(1),
                border_color=getattr(self, "queue_border", "#333333"),
            )
            empty.grid(row=0, column=0, sticky="ew", padx=S(6), pady=S(6))
            ctk.CTkLabel(
                empty,
                text="Queue is empty.",
                font=("Arial", S(14), "bold"),
                text_color=getattr(self, "queue_text_muted", "#9A9A9A"),
            ).pack(padx=S(14), pady=S(14))
            return

        image_by_name = {}
        for brawler, image in getattr(self, "queue_images", []):
            image_by_name[normalize_brawler_name(brawler)] = image

        for index, row in enumerate(self.queue_data):
            brawler = row.get("brawler", "")
            ptype = row.get("type", "trophies")
            target = row.get("push_until", "")
            current_value = row.get("wins", 0) if ptype == "wins" else row.get("trophies", 0)
            try:
                progress = min(1.0, max(0.0, float(current_value) / float(target))) if float(target) > 0 else 0.0
            except Exception:
                progress = 0.0

            card = ctk.CTkFrame(
                self.queue_list_frame,
                fg_color=getattr(self, "queue_bg_soft", "#242424"),
                corner_radius=S(12),
                border_width=S(1),
                border_color=getattr(self, "queue_border", "#333333"),
            )
            card.grid(row=index, column=0, sticky="ew", padx=S(6), pady=S(5))
            card.grid_columnconfigure(1, weight=1)

            img_tk = image_by_name.get(normalize_brawler_name(brawler))
            if img_tk:
                icon = ctk.CTkLabel(card, image=img_tk, text="")
                icon._spectro_image_ref = img_tk
                icon.grid(row=0, column=0, rowspan=3, padx=S(10), pady=S(10))
            else:
                fallback = ctk.CTkFrame(card, width=S(46), height=S(46), fg_color=getattr(self, "queue_bg_card", "#1f1f1f"), corner_radius=S(9))
                fallback.grid(row=0, column=0, rowspan=3, padx=S(10), pady=S(10))
                fallback.grid_propagate(False)
                ctk.CTkLabel(
                    fallback,
                    text=str(brawler)[:1].upper(),
                    text_color=getattr(self, "queue_accent", "#c0392b"),
                    font=("Arial", S(18), "bold"),
                ).place(relx=0.5, rely=0.5, anchor="center")

            display_name = str(brawler).replace("_", " ").title()
            ctk.CTkLabel(
                card,
                text=f"{index + 1}. {display_name}",
                font=("Arial", S(14), "bold"),
                text_color=getattr(self, "queue_text_main", "#FFFFFF"),
                anchor="w",
            ).grid(row=0, column=1, sticky="ew", padx=(0, S(8)), pady=(S(10), 0))

            ctk.CTkLabel(
                card,
                text=f"{current_value} / {target} {ptype}",
                font=("Arial", S(11), "bold"),
                text_color=getattr(self, "queue_text_muted", "#9A9A9A"),
                anchor="w",
            ).grid(row=1, column=1, sticky="ew", padx=(0, S(8)), pady=(S(1), 0))

            progress_bar = ctk.CTkProgressBar(
                card,
                height=S(7),
                fg_color=getattr(self, "queue_border", "#333333"),
                progress_color=getattr(self, "queue_accent_active", "#AA2A2A"),
            )
            progress_bar.grid(row=2, column=1, sticky="ew", padx=(0, S(8)), pady=(S(5), S(10)))
            progress_bar.set(progress)

            controls = ctk.CTkFrame(card, fg_color="transparent")
            controls.grid(row=0, column=2, rowspan=3, sticky="e", padx=(0, S(8)), pady=S(8))

            ctk.CTkButton(
                controls,
                text="↑",
                width=S(30),
                height=S(28),
                fg_color=getattr(self, "queue_bg_input", "#333333"),
                hover_color="#555555",
                command=lambda i=index: self._queue_move(i, -1),
            ).grid(row=0, column=0, padx=S(2), pady=S(2))
            ctk.CTkButton(
                controls,
                text="↓",
                width=S(30),
                height=S(28),
                fg_color=getattr(self, "queue_bg_input", "#333333"),
                hover_color="#555555",
                command=lambda i=index: self._queue_move(i, 1),
            ).grid(row=0, column=1, padx=S(2), pady=S(2))
            ctk.CTkButton(
                controls,
                text="✕",
                width=S(64),
                height=S(28),
                fg_color="#7d2020",
                hover_color="#a52a2a",
                command=lambda i=index: self._queue_remove(i),
            ).grid(row=1, column=0, columnspan=2, sticky="ew", padx=S(2), pady=S(2))

    @staticmethod
    def _api_brawler_unlocked(api_brawler):
        """Best-effort owned brawler check.

        Brawltracker normally returns owned brawlers, but some page layouts can expose
        zero-trophy cards. Treat a brawler as opened only when it has trophies, power,
        rank, or a similarly explicit owned marker.
        """
        def as_int(value, default=0):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return default

        trophies = as_int(api_brawler.get("trophies"))
        power = as_int(api_brawler.get("power"))
        rank = as_int(api_brawler.get("rank") or api_brawler.get("highestRank"))
        highest_trophies = as_int(api_brawler.get("highestTrophies") or api_brawler.get("highest_trophies"))
        return trophies > 0 or power > 0 or rank > 0 or highest_trophies > 0

    def _build_push_all_queue_from_player_data(self, player_data, target):
        known = {normalize_brawler_name(b): b for b in self.brawlers}
        rows = []
        skipped_locked = 0
        skipped_target = 0
        skipped_unknown = 0

        for index, api_brawler in enumerate(player_data.get("brawlers", [])):
            name = known.get(normalize_brawler_name(api_brawler.get("name", "")))
            if not name:
                skipped_unknown += 1
                continue
            if not self._api_brawler_unlocked(api_brawler):
                skipped_locked += 1
                continue
            try:
                trophies = int(float(api_brawler.get("trophies", 0)))
            except (TypeError, ValueError):
                trophies = 0
            if trophies >= target:
                skipped_target += 1
                continue
            rows.append((trophies, index, name, api_brawler))

        rows.sort(key=lambda item: (item[0], item[1], item[2]))
        data = []
        for trophies, _, name, api_brawler in rows:
            row = self._queue_row_template(name, target, "trophies")
            row["trophies"] = trophies
            row["power"] = int(api_brawler.get("power", 0) or 0)
            row["selection_method"] = "push_all_owned_below_target"
            row["automatically_pick"] = True
            data.append(row)

        return data, {
            "owned_below_target": len(data),
            "skipped_locked": skipped_locked,
            "skipped_target": skipped_target,
            "skipped_unknown": skipped_unknown,
        }

    def _queue_push_all(self):
        top = ctk.CTkToplevel(self.app)
        top.title("Push All")
        top.geometry(f"{S(380)}x{S(285)}")
        top.attributes("-topmost", True)
        top.configure(fg_color="#141414")

        card = ctk.CTkFrame(top, fg_color="#1f1f1f", corner_radius=S(14), border_width=1, border_color="#333333")
        card.pack(expand=True, fill="both", padx=S(14), pady=S(14))
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text="Push All",
            text_color="#FFFFFF",
            font=("Arial", S(22), "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=S(18), pady=(S(16), S(2)))
        ctk.CTkLabel(
            card,
            text="Build a queue only from opened brawlers that are below the target trophies.",
            text_color="#9A9A9A",
            font=("Arial", S(12)),
            anchor="w",
            justify="left",
            wraplength=S(310),
        ).grid(row=1, column=0, sticky="ew", padx=S(18), pady=(0, S(14)))

        ctk.CTkLabel(
            card,
            text="Target trophies",
            text_color="#9A9A9A",
            font=("Arial", S(12), "bold"),
            anchor="w",
        ).grid(row=2, column=0, sticky="w", padx=S(18), pady=(0, S(6)))
        target_var = tk.StringVar(value="1000")
        ctk.CTkEntry(
            card,
            textvariable=target_var,
            width=S(180),
            height=S(38),
            fg_color="#242424",
            border_color="#333333",
            text_color="#FFFFFF",
            font=("Arial", S(14)),
        ).grid(row=3, column=0, sticky="w", padx=S(18), pady=(0, S(12)))

        status_var = tk.StringVar(value="Only owned and below target brawlers will be added.")
        ctk.CTkLabel(
            card,
            textvariable=status_var,
            text_color="#9A9A9A",
            font=("Arial", S(11)),
            anchor="w",
            justify="left",
            wraplength=S(320),
        ).grid(row=4, column=0, sticky="ew", padx=S(18), pady=(0, S(12)))

        def run():
            try:
                target = int(float(target_var.get()))
                if target <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                status_var.set("Target must be a positive number.")
                return

            status_var.set("Loading player brawlers...")
            self._set_queue_status("Push All: loading player brawlers...")

            def worker():
                try:
                    api_config = load_brawl_stars_api_config("cfg/brawl_stars_api.toml")
                    player_data = fetch_brawl_stars_player(
                        api_config.get("api_token", "").strip(),
                        api_config.get("player_tag", "").strip(),
                        int(api_config.get("timeout_seconds", 15)),
                    )
                    data, stats = self._build_push_all_queue_from_player_data(player_data, target)
                except Exception as e:
                    self.app.after(0, lambda: status_var.set(f"API error: {e}"))
                    self.app.after(0, lambda: self._set_queue_status(f"Push All API error: {e}"))
                    return

                def apply_result():
                    self.queue_data = data
                    self._save_queue()
                    self._refresh_queue_list()
                    message = (
                        f"Push All: added {stats['owned_below_target']} opened brawlers below {target}. "
                        f"Skipped {stats['skipped_target']} already at target, "
                        f"{stats['skipped_locked']} locked/not confirmed."
                    )
                    status_var.set(message)
                    self._set_queue_status(message)
                    if data:
                        top.after(700, top.destroy)

                self.app.after(0, apply_result)

            threading.Thread(target=worker, daemon=True).start()

        ctk.CTkButton(
            card,
            text="Build Queue",
            fg_color="#c0392b",
            hover_color="#e74c3c",
            font=("Arial", S(15), "bold"),
            corner_radius=S(9),
            width=S(180),
            height=S(40),
            command=run,
        ).grid(row=5, column=0, sticky="w", padx=S(18), pady=(0, S(18)))

    # ---------------------------------------------------------------------------------------------
    #  On Start => close window + callback
    # ---------------------------------------------------------------------------------------------


    def _card(self, parent, row, column, title, subtitle="", columnspan=1):
        card = ctk.CTkFrame(parent, fg_color="#1f1f1f", corner_radius=S(14), border_width=1, border_color="#333333")
        card.grid(row=row, column=column, columnspan=columnspan, sticky="nsew", padx=S(8), pady=S(8))
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=0)
        ctk.CTkLabel(card, text=title, text_color="#FFFFFF", font=("Arial", S(19), "bold"), anchor="w").grid(row=0, column=0, columnspan=2, sticky="ew", padx=S(18), pady=(S(16), S(2)))
        if subtitle:
            ctk.CTkLabel(card, text=subtitle, text_color="#9A9A9A", font=("Arial", S(12)), anchor="w", justify="left", wraplength=S(760 if columnspan > 1 else 360)).grid(row=1, column=0, columnspan=2, sticky="ew", padx=S(18), pady=(0, S(14)))
            return card, 2
        return card, 1

    def _header(self, parent, title, subtitle):
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=S(8), pady=(S(4), S(10)))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=title, text_color="#FFFFFF", font=("Arial", S(30), "bold"), anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text=subtitle, text_color="#9A9A9A", font=("Arial", S(13)), anchor="w").grid(row=1, column=0, sticky="w", pady=(S(2), 0))

    def _scroll_root(self, frame):
        root = ctk.CTkScrollableFrame(frame, fg_color="transparent", scrollbar_button_color="#333333", scrollbar_button_hover_color="#BB3A3A")
        root.pack(expand=True, fill="both", padx=S(14), pady=S(10))
        root.grid_columnconfigure(0, weight=1)
        root.grid_columnconfigure(1, weight=1)
        return root

    def _setting_label(self, parent, row, label, hint=""):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=0, sticky="ew", padx=(S(18), S(30)), pady=S(7))
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text=label, text_color="#FFFFFF", font=("Arial", S(14), "bold"), anchor="w").grid(row=0, column=0, sticky="ew")
        if hint:
            ctk.CTkLabel(box, text=hint, text_color="#9A9A9A", font=("Arial", S(11)), anchor="w", justify="left", wraplength=S(220)).grid(row=1, column=0, sticky="ew")

    def _entry_setting(self, parent, row, label, config, path, key, convert=str, hint="", width=135):
        self._setting_label(parent, row, label, hint)
        var = tk.StringVar(value=str(config.get(key, "")))
        def save(*_):
            if getattr(self, "_applying_performance_profile", False):
                return
            try:
                config[key] = convert(var.get().strip())
                if callable(path):
                    path()
                else:
                    save_dict_as_toml(config, path)
            except Exception:
                var.set(str(config.get(key, "")))
        ent = ctk.CTkEntry(parent, textvariable=var, width=S(width), height=S(36), fg_color="#242424", border_color="#333333", text_color="#FFFFFF", font=("Arial", S(14)))
        ent.grid(row=row, column=1, sticky="e", padx=(S(8), S(18)), pady=S(7))
        ent.bind("<FocusOut>", save)
        ent.bind("<Return>", save)
        return var

    def _toggle_setting(self, parent, row, label, config, path, key, hint=""):
        self._setting_label(parent, row, label, hint)
        var = tk.BooleanVar(value=str(config.get(key, "no")).lower() in ("yes", "true", "1", "on"))
        def save():
            config[key] = "yes" if var.get() else "no"
            if callable(path):
                path()
            else:
                save_dict_as_toml(config, path)
        cb = ctk.CTkCheckBox(parent, text="Enabled", variable=var, command=save, fg_color="#AA2A2A", hover_color="#BB3A3A", border_color="#333333", text_color="#9A9A9A", font=("Arial", S(12), "bold"))
        cb.grid(row=row, column=1, sticky="e", padx=(S(8), S(18)), pady=S(7))
        return var

    def _option_setting(self, parent, row, label, variable, values, command, hint="", width=140):
        self._setting_label(parent, row, label, hint)
        menu = ctk.CTkOptionMenu(parent, variable=variable, values=values, command=command, width=S(width), height=S(36), fg_color="#333333", button_color="#AA2A2A", button_hover_color="#BB3A3A", dropdown_fg_color="#1f1f1f", dropdown_hover_color="#c0392b", dropdown_text_color="#FFFFFF", text_color="#FFFFFF", font=("Arial", S(13), "bold"), corner_radius=S(8))
        menu.grid(row=row, column=1, sticky="e", padx=(S(8), S(18)), pady=S(7))
        return menu

    def _init_additional_tab(self):
        root = self._scroll_root(self.tab_additional)
        self._header(root, "Additional Settings", "Advanced tuning grouped by purpose. Values save automatically.")
        entry_vars = {}

        performance, row = self._card(root, 1, 0, "Performance", "Capture speed, inference backend and quick presets.")
        gpu_var = tk.StringVar(value=str(self.general_config.get("cpu_or_gpu", "auto")))
        def gpu_change(choice):
            if getattr(self, "_applying_performance_profile", False):
                return
            self.general_config["cpu_or_gpu"] = choice
            save_dict_as_toml(self.general_config, self.general_config_path)
        self._option_setting(performance, row, "Inference Device", gpu_var, ["auto", "directml", "cuda", "openvino", "cpu"], gpu_change, "ONNX backend used by detection."); row += 1

        scrcpy_profile_values = ["custom"] + list(SCRCPY_CAPTURE_PROFILES.keys())
        scrcpy_profile_var = tk.StringVar(value=detect_scrcpy_capture_profile(self.general_config))
        scrcpy_status = ctk.CTkLabel(performance, text="", text_color="#9A9A9A", font=("Arial", S(12)), anchor="w")

        def refresh_scrcpy_entry_vars():
            for key in SCRCPY_CAPTURE_KEYS:
                var = entry_vars.get((True, key))
                if var is not None:
                    var.set(str(self.general_config.get(key, "")))

        def scrcpy_profile_change(choice):
            if choice == "custom" or getattr(self, "_applying_performance_profile", False):
                return
            try:
                clear_toml_cache(self.general_config_path)
                result = apply_scrcpy_capture_profile(choice, general_config_path=self.general_config_path)
                self.general_config.clear(); self.general_config.update(result["general_config"])
                refresh_scrcpy_entry_vars()
                scrcpy_profile_var.set(result["profile"])
                scrcpy_status.configure(
                    text=(
                        f"Applied {result['profile']}: "
                        f"{self.general_config.get('scrcpy_max_fps')} FPS, "
                        f"width {self.general_config.get('scrcpy_max_width')}, "
                        f"bitrate {self.general_config.get('scrcpy_bitrate')}. Restart the bot."
                    ),
                    text_color="#2ECC71",
                )
            except Exception as exc:
                scrcpy_status.configure(text=f"Could not apply scrcpy profile: {exc}", text_color="#E74C3C")

        self._option_setting(
            performance,
            row,
            "Scrcpy Capture Profile",
            scrcpy_profile_var,
            scrcpy_profile_values,
            scrcpy_profile_change,
            "Changes only scrcpy_max_fps, scrcpy_max_width and scrcpy_bitrate.",
            width=150,
        ); row += 1
        scrcpy_status.grid(row=row, column=0, columnspan=2, sticky="ew", padx=S(18), pady=(S(0), S(6))); row += 1

        for label, key, conv, hint in [
            ("DirectML GPU ID", "directml_device_id", str, "Usually auto, or 0 / 1."),
            ("Max IPS", "max_ips", lambda s: s if s.lower() == "auto" else int(s), "Bot image processing cap."),
            ("Scrcpy Max FPS", "scrcpy_max_fps", int, "Maximum emulator capture FPS."),
            ("Scrcpy Max Width", "scrcpy_max_width", int, "Maximum capture width sent by scrcpy."),
            ("Scrcpy Bitrate", "scrcpy_bitrate", int, "Video bitrate in bits per second."),
            ("Used Threads", "used_threads", lambda s: s if s.lower() == "auto" else int(s), "CPU threads for detection."),
        ]:
            entry_vars[(True, key)] = self._entry_setting(performance, row, label, self.general_config, self.general_config_path, key, conv, hint); row += 1
        profile_var = tk.StringVar(value="balanced")
        self._option_setting(performance, row, "Performance Profile", profile_var, ["balanced", "low-end", "quality"], lambda v: profile_var.set(v), "Applies safe preset values."); row += 1
        profile_status = ctk.CTkLabel(performance, text="", text_color="#9A9A9A", font=("Arial", S(12)), anchor="w")
        profile_status.grid(row=row, column=0, columnspan=2, sticky="ew", padx=S(18), pady=(S(4), 0)); row += 1
        def apply_profile():
            self._applying_performance_profile = True
            try:
                clear_toml_cache(self.general_config_path); clear_toml_cache(self.bot_config_path)
                result = apply_performance_profile(profile_var.get(), general_config_path=self.general_config_path, bot_config_path=self.bot_config_path)
                self.general_config.clear(); self.general_config.update(result["general_config"])
                self.bot_config.clear(); self.bot_config.update(result["bot_config"])
                gpu_var.set(str(self.general_config.get("cpu_or_gpu", "auto")))
                scrcpy_profile_var.set(detect_scrcpy_capture_profile(self.general_config))
                for (is_general, key), var in entry_vars.items():
                    cfg = self.general_config if is_general else self.bot_config
                    if key in cfg: var.set(str(cfg[key]))
                save_dict_as_toml(self.general_config, self.general_config_path); save_dict_as_toml(self.bot_config, self.bot_config_path)
                profile_status.configure(text=f"Applied {result['profile']} profile. Restart the bot to use it.", text_color="#2ECC71")
            except Exception as exc:
                profile_status.configure(text=f"Could not apply profile: {exc}", text_color="#E74C3C")
            finally:
                self.app.after(300, lambda: setattr(self, "_applying_performance_profile", False))
        ctk.CTkButton(performance, text="Apply Profile", command=apply_profile, fg_color="#AA2A2A", hover_color="#BB3A3A", width=S(140), height=S(38), corner_radius=S(9), font=("Arial", S(14), "bold")).grid(row=row, column=1, sticky="e", padx=(S(8), S(18)), pady=(S(8), S(18)))

        behavior, row = self._card(root, 1, 1, "Behavior", "Movement timing and gameplay behavior.")
        for label, key, conv, hint in [
            ("Movement Delay", "minimum_movement_delay", float, "Minimum movement hold time."),
            ("Unstuck Delay", "unstuck_movement_delay", float, "Before trying to unstuck."),
            ("Unstuck Duration", "unstuck_movement_hold_time", float, "How long unstuck movement lasts."),
            ("Playstyle", "current_playstyle", str, "File from playstyles folder."),
        ]:
            self._entry_setting(behavior, row, label, self.bot_config, self.bot_config_path, key, conv, hint); row += 1
        self._toggle_setting(behavior, row, "Play Again On Win", self.bot_config, self.bot_config_path, "play_again_on_win", "Press Play Again after wins."); row += 1
        self._toggle_setting(behavior, row, "Aimed Attacks", self.bot_config, self.bot_config_path, "aimed_attacks", "Drag the attack joystick toward the enemy before firing."); row += 1
        self._entry_setting(behavior, row, "Aim Radius", self.bot_config, self.bot_config_path, "aimed_attack_radius", float, "How far to drag attack joystick."); row += 1
        self._entry_setting(behavior, row, "Aim Duration", self.bot_config, self.bot_config_path, "aimed_attack_duration", float, "Seconds spent dragging attack joystick."); row += 1
        self._entry_setting(behavior, row, "Aim End Hold", self.bot_config, self.bot_config_path, "aimed_attack_end_hold", float, "Hold at final aim point before release."); row += 1
        self._toggle_setting(behavior, row, "Imitation Movement", self.bot_config, self.bot_config_path, "imitation_enabled", "Enable or disable learned movement policy."); row += 1
        self._toggle_setting(behavior, row, "Longpress Star Drop", self.general_config, self.general_config_path, "long_press_star_drop", "Use long press for star drops.")

        vision, row = self._card(root, 2, 0, "Vision", "Detection thresholds. Lower values detect more but can increase false detections.")
        for label, key, conv, hint in [
            ("Wall Confidence", "wall_detection_confidence", float, "Wall detection threshold."),
            ("Entity Confidence", "entity_detection_confidence", float, "Player and enemy threshold."),
            ("Super Pixels", "super_pixels_minimum", float, "Yellow pixels for super."),
            ("Gadget Pixels", "gadget_pixels_minimum", float, "Green pixels for gadget."),
            ("Hypercharge Pixels", "hypercharge_pixels_minimum", float, "Purple pixels for hypercharge."),
        ]:
            self._entry_setting(vision, row, label, self.bot_config, self.bot_config_path, key, conv, hint); row += 1
        self._entry_setting(vision, row, "OCR Scale", self.general_config, self.general_config_path, "ocr_scale_down_factor", float, "Brawler OCR scale.")

        debug, row = self._card(root, 2, 1, "Debug & Extras", "Logs, visual debugging and reward tweaks.")
        self._toggle_setting(debug, row, "Terminal Logging", self.general_config, self.general_config_path, "terminal_logging", "Save terminal output to logs."); row += 1
        self._toggle_setting(debug, row, "Debug Screen", self.general_config, self.general_config_path, "visual_debug", "Show OpenCV debug window."); row += 1
        self._toggle_setting(debug, row, "Capture Bad Frames", self.general_config, self.general_config_path, "capture_bad_vision_frames", "Save frames for model training."); row += 1
        self._entry_setting(debug, row, "Trophies Multiplier", self.general_config, self.general_config_path, "trophies_multiplier", float, "Reward multiplier.")

    def _init_webhook_tab(self):
        root = self._scroll_root(self.tab_webhook)
        self._header(root, "Integrations", "Telegram control, Discord notifications and Discord remote control.")
        def save_telegram():
            self.telegram_config_root["telegram"] = self.telegram_config
            save_dict_as_toml(self.telegram_config_root, self.telegram_config_path)
        telegram, row = self._card(root, 1, 0, "Telegram Control", "Remote control via Telegram. Starts with the bot after restart.", columnspan=2)
        self._toggle_setting(telegram, row, "Telegram Control", self.telegram_config, save_telegram, "enabled", "Commands: /menu, /status, /pause, /resume, /stop."); row += 1
        self._entry_setting(telegram, row, "Bot Token", self.telegram_config, save_telegram, "bot_token", str, "Token from BotFather.", width=260); row += 1
        self._entry_setting(telegram, row, "Chat ID", self.telegram_config, save_telegram, "chat_id", str, "Allowed Telegram chat id.", width=180); row += 1
        tg_status = ctk.CTkLabel(telegram, text="", text_color="#9A9A9A", font=("Arial", S(12)), anchor="w")
        tg_status.grid(row=row, column=0, columnspan=2, sticky="ew", padx=S(18), pady=(S(4), 0)); row += 1
        def test_tg():
            token = str(self.telegram_config.get("bot_token", "")).strip(); chat_id = str(self.telegram_config.get("chat_id", "")).strip()
            if not token or token == "YOUR_BOT_TOKEN" or not chat_id or chat_id == "YOUR_CHAT_ID":
                tg_status.configure(text="Set Bot Token and Chat ID first.", text_color="#E74C3C"); return
            def worker():
                try:
                    payload = json.dumps({"chat_id": chat_id, "text": "Spectro Telegram test OK."}).encode("utf-8")
                    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    self.app.after(0, lambda: tg_status.configure(text=("Telegram test sent." if data.get("ok") else str(data)), text_color=("#2ECC71" if data.get("ok") else "#E74C3C")))
                except Exception as exc:
                    self.app.after(0, lambda: tg_status.configure(text=f"Telegram test failed: {exc}", text_color="#E74C3C"))
            threading.Thread(target=worker, daemon=True).start()
        ctk.CTkButton(telegram, text="Send Telegram Test", command=test_tg, fg_color="#AA2A2A", hover_color="#BB3A3A", width=S(170)).grid(row=row, column=1, sticky="e", padx=(S(8), S(18)), pady=(S(8), S(18)))

        discord, row = self._card(root, 2, 0, "Discord Notifications", "Webhook notifications for match summaries and pings.")
        for label, key, hint, width in [("Webhook URL", "webhook_url", "Webhook URL.", 210), ("Discord ID", "discord_id", "User ID for pings.", 150), ("Webhook Name", "username", "Display name.", 150)]:
            self._entry_setting(discord, row, label, self.webhook_config, self.webhook_config_path, key, str, hint, width); row += 1
        for label, key, hint in [("Match Summary", "send_match_summary", "Send match summary."), ("Screenshots", "include_screenshot", "Attach screenshots."), ("Ping Stuck", "ping_when_stuck", "Ping when stuck."), ("Ping Target", "ping_when_target_is_reached", "Ping on target.")]:
            self._toggle_setting(discord, row, label, self.webhook_config, self.webhook_config_path, key, hint); row += 1
        d_status = ctk.CTkLabel(discord, text="", text_color="#9A9A9A", font=("Arial", S(12)), anchor="w")
        d_status.grid(row=row, column=0, columnspan=2, sticky="ew", padx=S(18), pady=(S(4), 0)); row += 1
        def test_discord():
            d_status.configure(text="Sending Discord test...", text_color="#9A9A9A")
            def worker():
                try:
                    ok = asyncio.run(async_send_test_notification())
                    self.app.after(0, lambda: d_status.configure(text=("Discord test sent." if ok else "Discord test failed."), text_color=("#2ECC71" if ok else "#E74C3C")))
                except Exception as exc:
                    self.app.after(0, lambda: d_status.configure(text=f"Discord test failed: {exc}", text_color="#E74C3C"))
            threading.Thread(target=worker, daemon=True).start()
        ctk.CTkButton(discord, text="Send Discord Test", command=test_discord, fg_color="#AA2A2A", hover_color="#BB3A3A", width=S(160)).grid(row=row, column=1, sticky="e", padx=(S(8), S(18)), pady=(S(8), S(18)))

        control, row = self._card(root, 2, 1, "Discord Control", "Remote control through a Discord bot.")
        self._toggle_setting(control, row, "Remote Control", self.webhook_config, self.webhook_config_path, "discord_control_enabled", "Enable Discord commands."); row += 1
        for label, key, hint in [("Bot Token", "discord_bot_token", "Bot token."), ("Allowed User", "discord_control_user_id", "Allowed user only."), ("Channel ID", "discord_control_channel_id", "Control channel."), ("Guild ID", "discord_control_guild_id", "Server ID.")]:
            self._entry_setting(control, row, label, self.webhook_config, self.webhook_config_path, key, str, hint, 170); row += 1

    def _init_updates_tab(self):
        UpdatePanel(self.tab_updates, scale_func=S, version=self.version_str)


    def _open_developer_console(self, title, args, cwd=None, description=""):
        """Open a dedicated console window and run a developer command inside it."""
        cwd = cwd or str(Path.cwd())
        window = ctk.CTkToplevel(self.app)
        window.title(f"Developer Console - {title}")
        window.geometry(f"{S(900)}x{S(620)}")
        window.minsize(S(720), S(460))
        window.attributes("-topmost", True)
        window.configure(fg_color="#141414")

        process_ref = {"process": None}

        root = ctk.CTkFrame(window, fg_color="transparent")
        root.pack(expand=True, fill="both", padx=S(14), pady=S(14))
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            root,
            text=title,
            text_color="#FFFFFF",
            font=("Arial", S(24), "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, S(2)))

        subtitle = description or "Running developer command. Output is streamed below."
        ctk.CTkLabel(
            root,
            text=subtitle,
            text_color="#9A9A9A",
            font=("Arial", S(12)),
            anchor="w",
            justify="left",
            wraplength=S(820),
        ).grid(row=1, column=0, sticky="ew", pady=(0, S(10)))

        command_box = ctk.CTkFrame(root, fg_color="#1f1f1f", corner_radius=S(12), border_width=1, border_color="#333333")
        command_box.grid(row=2, column=0, sticky="ew", pady=(0, S(10)))
        command_box.grid_columnconfigure(0, weight=1)
        command_text = "$ " + " ".join(str(part) for part in args)
        ctk.CTkLabel(
            command_box,
            text=command_text,
            text_color="#FFFFFF",
            font=("Consolas", S(12)),
            anchor="w",
            justify="left",
            wraplength=S(820),
        ).grid(row=0, column=0, sticky="ew", padx=S(12), pady=S(10))

        console = ctk.CTkTextbox(
            root,
            fg_color="#0f0f0f",
            border_color="#333333",
            border_width=1,
            text_color="#FFFFFF",
            font=("Consolas", S(12)),
            wrap="word",
        )
        console.grid(row=3, column=0, sticky="nsew")
        console.configure(state="disabled")

        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", pady=(S(10), 0))
        footer.grid_columnconfigure(0, weight=1)
        status = ctk.CTkLabel(footer, text="Starting...", text_color="#9A9A9A", font=("Arial", S(12)), anchor="w")
        status.grid(row=0, column=0, sticky="ew")

        def append(text):
            def apply():
                if not console.winfo_exists():
                    return
                console.configure(state="normal")
                console.insert("end", text)
                console.see("end")
                console.configure(state="disabled")
            try:
                window.after(0, apply)
            except tk.TclError:
                pass

        def set_status(text, color="#9A9A9A"):
            try:
                window.after(0, lambda: status.configure(text=text, text_color=color))
            except tk.TclError:
                pass

        def stop_process():
            proc = process_ref.get("process")
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    append("\nProcess termination requested.\n")
                    set_status("Stopping...", "#E67E22")
                except Exception as exc:
                    append(f"\nCould not stop process: {exc}\n")

        stop_btn = ctk.CTkButton(
            footer,
            text="Stop",
            command=stop_process,
            fg_color="#7d2020",
            hover_color="#a52a2a",
            font=("Arial", S(13), "bold"),
            width=S(90),
            height=S(34),
            corner_radius=S(9),
        )
        stop_btn.grid(row=0, column=1, padx=(S(8), 0))
        ctk.CTkButton(
            footer,
            text="Close",
            command=window.destroy,
            fg_color="#333333",
            hover_color="#555555",
            font=("Arial", S(13), "bold"),
            width=S(90),
            height=S(34),
            corner_radius=S(9),
        ).grid(row=0, column=2, padx=(S(8), 0))

        def worker():
            append(f"Working directory: {cwd}\n")
            append(command_text + "\n\n")
            code = -1
            try:
                process = subprocess.Popen(
                    args,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                process_ref["process"] = process
                set_status("Running...", "#9A9A9A")
                for line in process.stdout or []:
                    append(line)
                code = process.wait()
                if code == 0:
                    append("\nDone.\n")
                    set_status("Finished successfully.", "#2ECC71")
                else:
                    append(f"\nExit code: {code}\n")
                    set_status(f"Finished with exit code {code}.", "#E74C3C")
            except Exception as exc:
                append(f"\nERROR: {exc}\n")
                set_status("Failed.", "#E74C3C")
            finally:
                try:
                    window.after(0, lambda: stop_btn.configure(state="disabled"))
                except tk.TclError:
                    pass

        threading.Thread(target=worker, daemon=True).start()
        return window

    def _developer_open_path(self, path):
        try:
            target = Path(path).resolve()
            if not target.exists() and not target.suffix:
                target.mkdir(parents=True, exist_ok=True)
            os.startfile(str(target))
        except Exception as exc:
            self._open_developer_console("Open Path Error", ["open", str(path)], description=str(exc))

    def _developer_make_action(self, parent, row, title, description, args=None, accent=False, button_text="Run"):
        card = ctk.CTkFrame(parent, fg_color="#242424", corner_radius=S(12), border_width=1, border_color="#333333")
        card.grid(row=row, column=0, sticky="ew", padx=S(18), pady=S(6))
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            card,
            text=title,
            text_color="#FFFFFF",
            font=("Arial", S(14), "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=(S(12), S(22)), pady=(S(10), S(1)))
        ctk.CTkLabel(
            card,
            text=description,
            text_color="#9A9A9A",
            font=("Arial", S(11)),
            anchor="w",
            justify="left",
            wraplength=S(225),
        ).grid(row=1, column=0, sticky="ew", padx=(S(12), S(22)), pady=(0, S(10)))
        if args is not None:
            command = lambda: self._open_developer_console(title, args, cwd=str(Path.cwd()), description=description)
        else:
            command = lambda: None
        ctk.CTkButton(
            card,
            text=button_text,
            command=command,
            fg_color=("#AA2A2A" if accent else "#333333"),
            hover_color="#BB3A3A",
            text_color="#FFFFFF",
            font=("Arial", S(12), "bold"),
            width=S(82),
            height=S(32),
            corner_radius=S(9),
        ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(S(4), S(12)), pady=S(10))
        return card

    def _init_developer_tab(self):
        root = self._scroll_root(self.tab_developer)
        self._header(
            root,
            "Developer",
            "Practical launcher for tests, dataset capture and project utilities. Every command opens in its own console window.",
        )

        project_root = Path.cwd()
        python = sys.executable

        quick_card, row = self._card(root, 2, 0, "Quick Actions", "Common checks used before commits or releases.")
        quick_actions = [
            ("Run All Tests", "Run unittest discovery for the whole tests folder.", [python, "-m", "unittest", "discover", "-s", "tests"], True),
            ("Compile Project", "Compile Python files in main project folders to catch syntax errors.", [python, "-m", "compileall", "core", "game", "vision", "control", "gui", "integrations", "updates", "tools", "tests"], False),
            ("Pip Check", "Check installed packages for dependency conflicts.", [python, "-m", "pip", "check"], False),
            ("Auto Runtime Check", "Run automatic ONNX Runtime backend selection and print selected providers.", [python, "-m", "core.runtime_auto_config"], False),
        ]
        for title, desc, args, accent in quick_actions:
            self._developer_make_action(quick_card, row, title, desc, args, accent=accent)
            row += 1

        capture_card, row = self._card(root, 2, 1, "Dataset Capture", "Screenshot collection and dataset build helpers.")
        capture_actions = [
            ("Capture Wall Samples, 5 min", "Collect match screenshots for wall/bush model labeling. Saves to debug_frames/wall_vision.", [python, "tools/capture_wall_samples.py", "--seconds", "300", "--interval", "2.0"], True),
            ("Capture Wall Samples + Start Match", "Same capture, but also presses start from lobby and continues through non-match screens.", [python, "tools/capture_wall_samples.py", "--seconds", "300", "--interval", "2.0", "--start-match"], False),
            ("Capture Wall Samples, 10 min, 1s", "Longer capture session with one screenshot per second.", [python, "tools/capture_wall_samples.py", "--seconds", "600", "--interval", "1.0"], False),
            ("Capture Result Region", "Capture the exact trophy/result crop used by result detection.", [python, "tools/capture_result_region.py"], False),
            ("Build Wall Dataset", "Convert debug_frames/wall_vision into datasets/wall_model YOLO structure.", [python, "tools/create_wall_dataset.py"], False),
            ("Build Vision Dataset", "Build datasets/vision_model from debug_frames/vision metadata.", [python, "tools/create_vision_dataset.py", "--source", "debug_frames/vision", "--output", "datasets/vision_model", "--metadata-labels"], False),
        ]
        for title, desc, args, accent in capture_actions:
            self._developer_make_action(capture_card, row, title, desc, args, accent=accent)
            row += 1
        self._developer_make_action(capture_card, row, "Open Debug Frames", "Open folder with captured raw frames.", None, button_text="Open")
        capture_card.grid_slaves(row=row, column=0)[0].grid_slaves(row=0, column=1)[0].configure(command=lambda: self._developer_open_path("debug_frames"))
        row += 1
        self._developer_make_action(capture_card, row, "Open Datasets", "Open generated dataset folder.", None, button_text="Open")
        capture_card.grid_slaves(row=row, column=0)[0].grid_slaves(row=0, column=1)[0].configure(command=lambda: self._developer_open_path("datasets"))

        tests_card, row = self._card(root, 3, 0, "All Tests", "Every tests/test_*.py file. Each button opens a separate console.")
        test_files = sorted((project_root / "tests").glob("test_*.py"))
        if test_files:
            for test_file in test_files:
                module = f"tests.{test_file.stem}"
                title = test_file.stem.replace("test_", "").replace("_", " ").title()
                desc = f"Run unittest module {module}."
                self._developer_make_action(tests_card, row, title, desc, [python, "-m", "unittest", module])
                row += 1
        else:
            ctk.CTkLabel(tests_card, text="No tests found.", text_color="#9A9A9A", font=("Arial", S(12))).grid(row=row, column=0, padx=S(18), pady=S(12))

        tools_card, row = self._card(root, 3, 1, "All Utilities", "Every tools/*.py script. Scripts that require arguments can be launched from Custom Command.")
        tool_descriptions = {
            "capture_wall_samples.py": "Collect gameplay screenshots and raw wall detections for labeling.",
            "capture_result_region.py": "Capture the result/trophy crop from the live emulator.",
            "create_wall_dataset.py": "Create YOLO wall dataset from captured wall samples.",
            "create_vision_dataset.py": "Create a YOLO dataset from captured vision frames.",
            "pick_coordinate.py": "Pick 1920x1080 coordinates from a screenshot. Requires image path argument.",
            "github_update.py": "GitHub update helper used by Updates UI.",
            "apply_performance_profile.py": "Apply a performance profile from command line.",
            "performance_check.py": "Run quick performance and runtime diagnostics.",
            "fix_gpu_runtime.py": "GPU runtime repair helper.",
        }
        tool_files = sorted(
            file for file in (project_root / "tools").glob("*.py")
            if file.name != "__init__.py" and not file.name.startswith("_")
        )
        if tool_files:
            for tool_file in tool_files:
                title = tool_file.stem.replace("_", " ").title()
                rel = tool_file.relative_to(project_root).as_posix()
                desc = tool_descriptions.get(tool_file.name, f"Run utility script {rel}.")
                self._developer_make_action(
                    tools_card,
                    row,
                    title,
                    desc,
                    [python, rel],
                    accent=(tool_file.name == "capture_wall_samples.py"),
                )
                row += 1
        else:
            ctk.CTkLabel(tools_card, text="No tools found.", text_color="#9A9A9A", font=("Arial", S(12))).grid(row=row, column=0, padx=S(18), pady=S(12))
        self._developer_make_action(tools_card, row, "Open Tools Folder", "Open the tools folder in Explorer.", None, button_text="Open")
        tools_card.grid_slaves(row=row, column=0)[0].grid_slaves(row=0, column=1)[0].configure(command=lambda: self._developer_open_path("tools"))
        row += 1
        self._developer_make_action(tools_card, row, "Open Logs Folder", "Open logs folder in Explorer.", None, button_text="Open")
        tools_card.grid_slaves(row=row, column=0)[0].grid_slaves(row=0, column=1)[0].configure(command=lambda: self._developer_open_path("logs"))

        custom_card, row = self._card(
            root,
            1,
            0,
            "Custom Command",
            "Run a custom command in the project folder. A new console window will open for the command.",
            columnspan=2,
        )
        custom_card.grid_columnconfigure(0, weight=1)
        self.developer_custom_var = tk.StringVar(value="python tools/capture_wall_samples.py --seconds 60 --interval 1")
        custom_entry = ctk.CTkEntry(
            custom_card,
            textvariable=self.developer_custom_var,
            fg_color="#242424",
            border_color="#333333",
            text_color="#FFFFFF",
            placeholder_text="python tools/capture_wall_samples.py --seconds 60 --interval 1",
            font=("Consolas", S(12)),
            height=S(38),
        )
        custom_entry.grid(row=row, column=0, sticky="ew", padx=S(18), pady=(0, S(12)))

        def run_custom():
            import shlex
            cmd = self.developer_custom_var.get().strip()
            if not cmd:
                return
            if cmd.startswith("python "):
                parts = [python] + shlex.split(cmd)[1:]
            elif cmd.startswith("py "):
                parts = [python] + shlex.split(cmd)[1:]
            else:
                parts = shlex.split(cmd)
            self._open_developer_console("Custom Command", parts, cwd=str(project_root), description="Custom developer command.")

        ctk.CTkButton(
            custom_card,
            text="Run",
            command=run_custom,
            fg_color="#AA2A2A",
            hover_color="#BB3A3A",
            font=("Arial", S(13), "bold"),
            width=S(110),
            height=S(38),
            corner_radius=S(9),
        ).grid(row=row, column=1, sticky="e", padx=(S(8), S(18)), pady=(0, S(12)))
        custom_entry.bind("<Return>", lambda _e: run_custom())

    def _init_timers_tab(self):
        root = self._scroll_root(self.tab_timers)
        self._header(root, "Timers", "Tune how often Spectro checks combat actions and recovery states.")
        def timer_row(parent, row, key, title, hint, from_=0.1, to=10.0):
            box = ctk.CTkFrame(parent, fg_color="#242424", corner_radius=S(10))
            box.grid(row=row, column=0, sticky="ew", padx=S(18), pady=S(6)); box.grid_columnconfigure(0, weight=1)
            top = ctk.CTkFrame(box, fg_color="transparent"); top.grid(row=0, column=0, sticky="ew", padx=S(12), pady=(S(10), S(2))); top.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(top, text=title, text_color="#FFFFFF", font=("Arial", S(14), "bold"), anchor="w").grid(row=0, column=0, sticky="w")
            var = tk.StringVar(value=str(self.time_tresholds.get(key, 1)))
            ent = ctk.CTkEntry(top, textvariable=var, width=S(74), height=S(32), fg_color="#333333", border_color="#333333", text_color="#FFFFFF", font=("Arial", S(13), "bold")); ent.grid(row=0, column=1, sticky="e")
            ctk.CTkLabel(box, text=hint, text_color="#9A9A9A", font=("Arial", S(11)), anchor="w").grid(row=1, column=0, sticky="ew", padx=S(12), pady=(0, S(7)))
            slider = ctk.CTkSlider(box, from_=from_, to=to, number_of_steps=99, fg_color="#333333", progress_color="#AA2A2A", button_color="#c0392b", button_hover_color="#BB3A3A")
            slider.grid(row=2, column=0, sticky="ew", padx=S(12), pady=(0, S(12)))
            def save(value, set_slider=False):
                try: val = max(from_, min(to, float(value)))
                except Exception: val = float(self.time_tresholds.get(key, 1))
                self.time_tresholds[key] = val; save_dict_as_toml(self.time_tresholds, self.time_tresholds_path); var.set(f"{val:.2f}")
                if set_slider: slider.set(val)
            slider.configure(command=lambda v: save(v, False)); ent.bind("<FocusOut>", lambda e: save(var.get(), True)); ent.bind("<Return>", lambda e: save(var.get(), True))
            save(self.time_tresholds.get(key, 1), True)
        combat, row = self._card(root, 1, 0, "Combat Checks", "Fast checks for abilities.")
        timer_row(combat, row, "super", "Super Delay", "How often the bot checks if super is ready."); row += 1
        timer_row(combat, row, "hypercharge", "Hypercharge Delay", "How often the bot checks if hypercharge is ready."); row += 1
        timer_row(combat, row, "gadget", "Gadget Check Delay", "How often the bot checks if gadget is ready.")
        recovery, row = self._card(root, 1, 1, "Recovery Checks", "State and map checks used for recovery.")
        timer_row(recovery, row, "wall_detection", "Wall Detection", "How often the bot detects walls around the player."); row += 1
        timer_row(recovery, row, "no_detection_proceed", "No Detection Proceed", "How often the bot presses Q when it cannot detect state.")

    def _reset_match_history(self):
        self.match_history = {"total": {"victory": 0, "defeat": 0, "draw": 0}}
        save_dict_as_toml(self.match_history, self.match_history_path)
        clear_toml_cache(self.match_history_path)
        for child in self.tab_history.winfo_children():
            child.destroy()
        self._init_history_tab()
        print("Match history reset.")

    def _init_history_tab(self):
        root = self._scroll_root(self.tab_history)
        self._header(root, "Match History", "Compact stats by brawler, sorted by activity.")
        items = []; total_victory = total_defeat = total_draw = 0
        for brawler, stats in self.match_history.items():
            if brawler == "total" or not isinstance(stats, dict): continue
            victory = int(stats.get("victory", 0) or 0); defeat = int(stats.get("defeat", 0) or 0); draw = int(stats.get("draw", 0) or 0)
            games = victory + defeat + draw
            total_victory += victory; total_defeat += defeat; total_draw += draw
            if games: items.append({"name": brawler, "victory": victory, "defeat": defeat, "draw": draw, "games": games, "wr": round(100 * victory / games, 1)})
        items.sort(key=lambda x: (x["games"], x["wr"]), reverse=True)
        total_games = total_victory + total_defeat + total_draw; total_wr = round(100 * total_victory / total_games, 1) if total_games else 0
        summary = ctk.CTkFrame(root, fg_color="#1f1f1f", corner_radius=S(14), border_width=1, border_color="#333333")
        summary.grid(row=1, column=0, columnspan=2, sticky="ew", padx=S(8), pady=S(8))
        for col, (title, value, color) in enumerate([("Total Games", total_games, "#FFFFFF"), ("Win Rate", f"{total_wr}%", "#2ecc71" if total_wr >= 50 else "#e74c3c"), ("Wins", total_victory, "#2ecc71"), ("Losses", total_defeat, "#e74c3c")]):
            summary.grid_columnconfigure(col, weight=1)
            box = ctk.CTkFrame(summary, fg_color="#242424", corner_radius=S(10)); box.grid(row=0, column=col, sticky="ew", padx=S(8), pady=S(10))
            ctk.CTkLabel(box, text=title, text_color="#9A9A9A", font=("Arial", S(11), "bold")).pack(pady=(S(10), S(2)))
            ctk.CTkLabel(box, text=str(value), text_color=color, font=("Arial", S(22), "bold")).pack(pady=(0, S(10)))
        summary.grid_columnconfigure(4, weight=0)
        reset_box = ctk.CTkFrame(summary, fg_color="#242424", corner_radius=S(10))
        reset_box.grid(row=0, column=4, sticky="nsew", padx=S(8), pady=S(10))
        ctk.CTkLabel(reset_box, text="Actions", text_color="#9A9A9A", font=("Arial", S(11), "bold")).pack(pady=(S(10), S(6)))
        ctk.CTkButton(
            reset_box,
            text="Reset History",
            command=self._reset_match_history,
            fg_color="#7d2020",
            hover_color="#a52a2a",
            font=("Arial", S(12), "bold"),
            width=S(120),
            height=S(34),
            corner_radius=S(9),
        ).pack(padx=S(10), pady=(0, S(10)))
        list_frame = ctk.CTkScrollableFrame(root, fg_color="transparent", height=S(500), scrollbar_button_color="#333333", scrollbar_button_hover_color="#BB3A3A")
        list_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=S(8), pady=S(8))
        for col in range(3): list_frame.grid_columnconfigure(col, weight=1)
        if not items:
            ctk.CTkLabel(list_frame, text="No match history yet.", text_color="#9A9A9A", font=("Arial", S(16), "bold")).grid(row=0, column=0, sticky="w", padx=S(18), pady=S(18)); return
        self.history_icon_refs = []
        for index, item in enumerate(items):
            card = ctk.CTkFrame(list_frame, fg_color="#1f1f1f", corner_radius=S(12), border_width=1, border_color="#333333")
            card.grid(row=index // 3, column=index % 3, sticky="ew", padx=S(6), pady=S(6)); card.grid_columnconfigure(1, weight=1)
            icon_path = f"./api/assets/brawler_icons/{item['name']}.png"; icon_img = None
            if os.path.exists(icon_path):
                try:
                    pil = Image.open(icon_path).resize((S(52), S(52))); icon_img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(S(52), S(52))); self.history_icon_refs.append(icon_img)
                except Exception: icon_img = None
            if icon_img: ctk.CTkLabel(card, image=icon_img, text="").grid(row=0, column=0, rowspan=3, padx=S(10), pady=S(10))
            else: ctk.CTkLabel(card, text=str(item["name"])[:1].upper(), text_color="#c0392b", font=("Arial", S(22), "bold"), width=S(52)).grid(row=0, column=0, rowspan=3, padx=S(10), pady=S(10))
            ctk.CTkLabel(card, text=str(item["name"]).replace("_", " ").title(), text_color="#FFFFFF", font=("Arial", S(14), "bold"), anchor="w").grid(row=0, column=1, sticky="ew", padx=(0, S(10)), pady=(S(10), 0))
            ctk.CTkLabel(card, text=f"{item['games']} games  •  {item['wr']}% WR", text_color=("#2ecc71" if item["wr"] >= 50 else "#e74c3c"), font=("Arial", S(12), "bold"), anchor="w").grid(row=1, column=1, sticky="ew", padx=(0, S(10)))
            ctk.CTkLabel(card, text=f"W {item['victory']}   L {item['defeat']}   D {item['draw']}", text_color="#9A9A9A", font=("Arial", S(11)), anchor="w").grid(row=2, column=1, sticky="ew", padx=(0, S(10)), pady=(0, S(10)))

    def _close_app_window(self):
        try:
            for after_id in self.app.tk.call("after", "info"):
                try:
                    self.app.after_cancel(after_id)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self._hide_tooltip()
        except Exception:
            pass
        try:
            self.app.withdraw()
            self.app.update_idletasks()
        except Exception:
            pass
        try:
            self.app.quit()
        except Exception:
            pass
        try:
            self.app.destroy()
        except Exception:
            pass

    def _on_close(self):
        self.start_requested = False
        self.closed_by_user = True
        self._close_app_window()

    def _on_start(self):
        self.start_requested = True
        self.closed_by_user = False
        self._close_app_window()

        if callable(self.on_close_callback):
            self.on_close_callback()
