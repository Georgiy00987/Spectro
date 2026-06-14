"""Spectro launcher."""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
os.chdir(_here)


import ctypes

def setup_windows_app_id():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Spectro.Bot")
    except Exception:
        pass

setup_windows_app_id()

from core.runtime_auto_config import configure_runtime_auto
configure_runtime_auto()

from core.config_validator import validate_all_configs
validate_all_configs()

from main import main

if __name__ == "__main__":
    main()
