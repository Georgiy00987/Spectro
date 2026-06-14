import os
import sys
import tkinter as tk
import time

import customtkinter as ctk
from core import utils
from core.utils import api_base_url

sys.path.append(os.path.abspath('../'))


def patch_tk_cleanup_errors():
    if getattr(tk.Variable, "_spectro_safe_del", False):
        return

    original_del = tk.Variable.__del__

    def safe_del(self):
        try:
            original_del(self)
        except (RuntimeError, tk.TclError) as e:
            message = str(e)
            if (
                    "main thread is not in main loop" in message
                    or "application has been destroyed" in message
                    or "invalid command name" in message
            ):
                return
            raise

    tk.Variable.__del__ = safe_del
    tk.Variable._spectro_safe_del = True


def install_tk_background_error_filter(root):
    def spectro_bgerror(message):
        message = str(message)
        if (
                "invalid command name" in message
                and (
                    "update" in message
                    or "check_dpi_scaling" in message
                    or "_click_animation" in message
                )
        ):
            return
        print(message)

    try:
        root.tk.createcommand("spectro_bgerror", spectro_bgerror)
        root.tk.call("proc", "bgerror", "message", "spectro_bgerror $message")
    except Exception:
        pass


class App:

    def __init__(self, login_page, select_brawler_page, spectro_main, brawlers, hub_menu):
        self.login = login_page
        self.select_brawler = select_brawler_page
        self.logged_in = False
        self.brawler_data = None
        self.spectro_main = spectro_main
        self.brawlers = brawlers
        self.hub_menu = hub_menu

    def set_is_logged(self, value):
        self.logged_in = value

    def set_data(self, value):
        self.brawler_data = value

    def start(self, spectro_version, get_latest_version):
        patch_tk_cleanup_errors()
        self.login(self.set_is_logged)
        if self.logged_in:
            latest = spectro_version if api_base_url == "localhost" else get_latest_version()
            hub = self.hub_menu(spectro_version, latest, brawlers=self.brawlers)
            if not getattr(hub, "start_requested", False):
                print("Spectro Hub was closed without Start; exiting.")
                return
            utils.clear_toml_cache()
            self.brawler_data = utils.load_brawler_data()
            if self.brawler_data:
                self.spectro_main(self.brawler_data)
            else:
                print("Очередь бойцов пуста — добавь бойцов во вкладке 'Brawler Queue' в хабе.")
