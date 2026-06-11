from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from core.utils import load_toml_as_dict

_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramControl:
    """Lightweight Telegram bot for Spectro remote control."""

    def __init__(self, state_path, state_reader=None):
        self.state_path  = Path(state_path)
        self.state_reader = state_reader or (lambda: {})
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        cfg = self._cfg()
        if not cfg.get("enabled", False): return False
        token   = str(cfg.get("bot_token", "")).strip()
        chat_id = str(cfg.get("chat_id",   "")).strip()
        if not token or token == "YOUR_BOT_TOKEN":
            print("[Telegram] bot_token not set in cfg/telegram_config.toml")
            return False
        if not chat_id or chat_id == "YOUR_CHAT_ID":
            print("[Telegram] chat_id not set in cfg/telegram_config.toml")
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="TelegramCtrl")
        self._thread.start()
        print("[Telegram] Control bot started.")
        return True

    def stop(self): self._stop_event.set()

    def notify(self, text):
        threading.Thread(target=self._send_notify, args=(text,), daemon=True).start()

    def _cfg(self):
        return load_toml_as_dict("cfg/telegram_config.toml").get("telegram", {})

    def _api(self, token, method, payload, timeout=30):
        url  = _API.format(token=token, method=method)
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def _get_updates(self, token, offset, timeout):
        url    = _API.format(token=token, method="getUpdates")
        params = f"?offset={offset}&timeout={timeout}&allowed_updates=%5B%22message%22%2C%22callback_query%22%5D"
        try:
            with urllib.request.urlopen(url + params, timeout=timeout + 10) as resp:
                return json.loads(resp.read()).get("result", [])
        except (urllib.error.URLError, TimeoutError, OSError): return []
        except Exception as e:
            print(f"[Telegram] poll error: {e}"); return []

    def _send_notify(self, text):
        cfg = self._cfg()
        token   = str(cfg.get("bot_token", "")).strip()
        chat_id = str(cfg.get("chat_id",   "")).strip()
        if not token or not chat_id: return
        try:
            self._api(token, "sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        except Exception: pass

    def _status_text(self):
        try:
            s = self.state_reader()
            return (
                f"<b>Spectro</b>\n"
                f"Status:   {s.get('status',     '?')}\n"
                f"Brawler:  {s.get('brawler',    '-')}\n"
                f"Trophies: {s.get('trophies',   '-')}\n"
                f"Game:     {s.get('game_state', '-')}\n"
                f"Uptime:   {s.get('uptime',     '-')}"
            )
        except Exception: return "Status unavailable"

    def _keyboard(self):
        try:
            from app.runtime_control import read_state, PAUSED
            paused = read_state(self.state_path) == PAUSED
        except Exception: paused = False
        toggle_text   = "▶ Resume" if paused else "⏸ Pause"
        toggle_action = "resume"   if paused else "pause"
        return {"inline_keyboard": [
            [{"text": toggle_text, "callback_data": toggle_action},
             {"text": "📊 Status",  "callback_data": "status"}],
            [{"text": "🛑 Stop bot", "callback_data": "stop"}],
        ]}

    def _send_menu(self, token, chat_id):
        self._api(token, "sendMessage", {
            "chat_id": chat_id, "text": self._status_text(),
            "parse_mode": "HTML", "reply_markup": self._keyboard(),
        })

    def _do_pause(self, token, chat_id):
        try:
            from app.runtime_control import write_state, PAUSED
            write_state(self.state_path, PAUSED)
            self._api(token, "sendMessage", {"chat_id": chat_id, "text": "⏸ Paused."})
        except Exception as e:
            self._api(token, "sendMessage", {"chat_id": chat_id, "text": f"Error: {e}"})

    def _do_resume(self, token, chat_id):
        try:
            from app.runtime_control import write_state, RUNNING
            write_state(self.state_path, RUNNING)
            self._api(token, "sendMessage", {"chat_id": chat_id, "text": "▶ Resumed."})
        except Exception as e:
            self._api(token, "sendMessage", {"chat_id": chat_id, "text": f"Error: {e}"})

    def _do_stop(self, token, chat_id):
        self._api(token, "sendMessage", {"chat_id": chat_id, "text": "🛑 Stopping..."})
        self._stop_event.set()
        try:
            from app.runtime_control import write_state
            write_state(self.state_path, "stop")
        except Exception: pass

    def _handle(self, token, chat_id, update):
        msg = update.get("message", {})
        cb  = update.get("callback_query", {})
        if msg:
            if str(msg.get("chat", {}).get("id", "")) != chat_id: return
            text = msg.get("text", "").strip().lower()
            if text in ("/start", "/menu"): self._send_menu(token, chat_id)
            elif text == "/status": self._api(token, "sendMessage", {"chat_id": chat_id, "text": self._status_text(), "parse_mode": "HTML"})
            elif text == "/pause": self._do_pause(token, chat_id)
            elif text == "/resume": self._do_resume(token, chat_id)
            elif text == "/stop": self._do_stop(token, chat_id)
        elif cb:
            if str(cb.get("message", {}).get("chat", {}).get("id", "")) != chat_id: return
            cb_id = cb.get("id", ""); data = cb.get("data", "")
            try: self._api(token, "answerCallbackQuery", {"callback_query_id": cb_id})
            except Exception: pass
            if   data == "status": self._api(token, "sendMessage", {"chat_id": chat_id, "text": self._status_text(), "parse_mode": "HTML"})
            elif data == "pause":  self._do_pause(token, chat_id)
            elif data == "resume": self._do_resume(token, chat_id)
            elif data == "stop":   self._do_stop(token, chat_id)

    def _loop(self):
        cfg          = self._cfg()
        token        = str(cfg.get("bot_token",    "")).strip()
        chat_id      = str(cfg.get("chat_id",      "")).strip()
        poll_timeout = int(cfg.get("poll_timeout", 20))
        idle_sleep   = int(cfg.get("idle_sleep",   8))
        offset       = 0
        try: self._send_menu(token, chat_id)
        except Exception: pass
        while not self._stop_event.is_set():
            updates = self._get_updates(token, offset, poll_timeout)
            if updates:
                for upd in updates:
                    try: self._handle(token, chat_id, upd)
                    except Exception as e: print(f"[Telegram] handle error: {e}")
                    offset = upd["update_id"] + 1
            else:
                self._stop_event.wait(idle_sleep)