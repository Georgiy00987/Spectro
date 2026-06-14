import os
import subprocess
import sys
import time
import ctypes
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


RUNNING = "running"
PAUSED = "paused"
STOP = "stop"


def write_state(path, state):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(state, encoding="utf-8")


def read_state(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip().lower()
    except OSError:
        return RUNNING


def metrics_path_for(state_path):
    return Path(state_path).with_suffix(".ips")


def details_path_for(state_path):
    return Path(state_path).with_suffix(".json")


def read_ips(path):
    try:
        return float(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def read_details(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


class RuntimeControlWindow:
    def __init__(self):
        state_dir = Path("logs").resolve()
        self.state_path = state_dir / f"runtime_control_{os.getpid()}.state"
        self.metrics_path = metrics_path_for(self.state_path)
        self.details_path = details_path_for(self.state_path)
        self.process = None
        write_state(self.state_path, RUNNING)
        self._clear_metrics()

    def _clear_metrics(self):
        try:
            if self.metrics_path.exists():
                self.metrics_path.unlink()
            if self.details_path.exists():
                self.details_path.unlink()
        except OSError:
            pass

    def start(self):
        if self.process and self.process.poll() is None:
            return
        script_path = Path(__file__).resolve()
        self.process = subprocess.Popen(
            [sys.executable, str(script_path), "--window", str(self.state_path)],
            cwd=str(script_path.parent.parent),
            close_fds=True,
        )
        time.sleep(0.2)
        if self.process.poll() is not None:
            print("Runtime pause control window failed to start.")

    def update_ips(self, ips):
        """Publish the latest IPS so the control window can display it."""
        if ips is None:
            return
        try:
            self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
            self.metrics_path.write_text(f"{float(ips):.2f}", encoding="utf-8")
        except (OSError, ValueError, TypeError):
            pass

    def update_details(self, brawler=None, trophies=None, game_state=None):
        """Publish compact bot details for the control window."""
        data = {
            "brawler": brawler or "-",
            "trophies": "-" if trophies in (None, "") else trophies,
            "game_state": game_state or "unknown",
            "updated_at": time.time(),
        }
        try:
            self.details_path.parent.mkdir(parents=True, exist_ok=True)
            self.details_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass

    def is_paused(self):
        return read_state(self.state_path) == PAUSED

    def is_stop_requested(self):
        return read_state(self.state_path) == STOP

    def close(self):
        write_state(self.state_path, RUNNING)
        self._clear_metrics()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


def process_is_alive(pid):
    if not pid or pid == os.getpid():
        return True
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    process_query_limited_information = 0x1000
    still_active = 259
    handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, int(pid))
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def format_uptime(seconds):
    seconds = int(max(0, seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def run_window(state_path):
    import tkinter as tk
    import customtkinter as ctk
    from core.window_icon import set_window_icon, set_windows_app_id

    set_windows_app_id("Spectro.ControlPanel")

    metrics_path = metrics_path_for(state_path)
    details_path = details_path_for(state_path)

    ctk.set_appearance_mode("dark")

    BG = "#1B1B1B"
    BOX = "#2B2B2B"
    TEXT = "#FFFFFF"
    MUTED = "#8C8C8C"
    OK = "#2FCE66"
    PAUSE_CLR = "#FFB23F"
    BLUE = "#3A6FB0"
    BLUE_H = "#4A82C7"
    GREEN = "#2F8F4E"
    GREEN_H = "#3DAF62"
    RED = "#AA2A2A"
    RED_H = "#BB3A3A"

    root = ctk.CTk()
    root.title("Spectro Control")
    root.geometry("320x370")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.configure(fg_color=BG)
    set_window_icon(root)
    root.after(100, lambda: set_window_icon(root))

    owner_pid = None
    try:
        owner_pid = int(Path(state_path).stem.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        owner_pid = None

    started_at = time.time()

    ips_var = tk.StringVar(value="\u2014")
    status_var = tk.StringVar(value="Running")
    uptime_var = tk.StringVar(value="00:00")
    brawler_var = tk.StringVar(value="-")
    trophies_var = tk.StringVar(value="-")
    game_state_var = tk.StringVar(value="unknown")
    pause_btn_var = tk.StringVar(value="PAUSE")

    def root_exists():
        try:
            return bool(root.winfo_exists())
        except tk.TclError:
            return False

    def toggle_pause():
        current = read_state(state_path)
        write_state(state_path, RUNNING if current == PAUSED else PAUSED)
        refresh()

    def do_stop():
        write_state(state_path, STOP)
        root.destroy()

    def on_close():
        # Closing the window should not freeze the bot: fall back to running.
        write_state(state_path, RUNNING)
        root.destroy()

    def refresh():
        if owner_pid and not process_is_alive(owner_pid):
            root.destroy()
            return
        paused = read_state(state_path) == PAUSED
        status_var.set("Paused" if paused else "Running")
        status_value.configure(text_color=PAUSE_CLR if paused else OK)
        pause_btn_var.set("RESUME" if paused else "PAUSE")
        pause_button.configure(
            fg_color=GREEN if paused else BLUE,
            hover_color=GREEN_H if paused else BLUE_H,
        )
        ips = read_ips(metrics_path)
        ips_var.set(f"{ips:.1f}" if ips is not None else "\u2014")
        uptime_var.set(format_uptime(time.time() - started_at))
        details = read_details(details_path)
        brawler_var.set(str(details.get("brawler") or "-"))
        trophies_var.set(str(details.get("trophies") if details.get("trophies") not in (None, "") else "-"))
        game_state_var.set(str(details.get("game_state") or "unknown"))

    def refresh_loop():
        if not root_exists():
            return
        refresh()
        if root_exists():
            root.after(100, refresh_loop)

    # --- Title (bot name) ---
    title = ctk.CTkLabel(root, text="Spectro", text_color=TEXT, font=("Arial", 18, "bold"))
    title.pack(pady=(14, 10))

    # --- Two stat boxes: IPS | STATUS ---
    boxes = ctk.CTkFrame(root, fg_color="transparent")
    boxes.pack(fill="x", padx=14)
    boxes.grid_columnconfigure(0, weight=1, uniform="box")
    boxes.grid_columnconfigure(1, weight=1, uniform="box")

    ips_box = ctk.CTkFrame(boxes, fg_color=BOX, corner_radius=10)
    ips_box.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
    ctk.CTkLabel(ips_box, text="IPS", text_color=MUTED, font=("Arial", 11, "bold")).pack(pady=(10, 0))
    ctk.CTkLabel(ips_box, textvariable=ips_var, text_color=TEXT, font=("Arial", 24, "bold")).pack(pady=(0, 11))

    status_box = ctk.CTkFrame(boxes, fg_color=BOX, corner_radius=10)
    status_box.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
    ctk.CTkLabel(status_box, text="STATUS", text_color=MUTED, font=("Arial", 11, "bold")).pack(pady=(10, 0))
    status_value = ctk.CTkLabel(status_box, textvariable=status_var, text_color=OK, font=("Arial", 18, "bold"))
    status_value.pack(pady=(4, 13))

    # --- Minimal bot details ---
    info = ctk.CTkFrame(root, fg_color=BOX, corner_radius=10)
    info.pack(fill="x", padx=14, pady=12)

    def add_info_row(label, variable, top_pad=8):
        row = ctk.CTkFrame(info, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(top_pad, 0))
        ctk.CTkLabel(row, text=label, text_color=MUTED, font=("Arial", 11, "bold"), width=82, anchor="w").pack(side="left")
        ctk.CTkLabel(row, textvariable=variable, text_color=TEXT, font=("Arial", 14, "bold"), anchor="w").pack(side="left", fill="x", expand=True)

    add_info_row("BRAWLER", brawler_var)
    add_info_row("TROPHIES", trophies_var, 5)
    add_info_row("GAME", game_state_var, 5)
    add_info_row("UPTIME", uptime_var, 5)
    ctk.CTkLabel(info, text="", height=6).pack()

    # --- Buttons: PAUSE | STOP ---
    btns = ctk.CTkFrame(root, fg_color="transparent")
    btns.pack(fill="x", padx=14, pady=(0, 14))
    btns.grid_columnconfigure(0, weight=1, uniform="btn")
    btns.grid_columnconfigure(1, weight=1, uniform="btn")

    pause_button = ctk.CTkButton(
        btns,
        textvariable=pause_btn_var,
        command=toggle_pause,
        height=42,
        corner_radius=8,
        fg_color=BLUE,
        hover_color=BLUE_H,
        text_color=TEXT,
        font=("Arial", 16, "bold"),
    )
    pause_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))

    stop_button = ctk.CTkButton(
        btns,
        text="STOP",
        command=do_stop,
        height=42,
        corner_radius=8,
        fg_color=RED,
        hover_color=RED_H,
        text_color=TEXT,
        font=("Arial", 16, "bold"),
    )
    stop_button.grid(row=0, column=1, sticky="ew", padx=(5, 0))

    root.protocol("WM_DELETE_WINDOW", on_close)
    refresh_loop()
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--window":
        run_window(sys.argv[2])
