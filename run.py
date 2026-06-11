"""Spectro launcher."""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
os.chdir(_here)

from core.runtime_auto_config import configure_runtime_auto
configure_runtime_auto()

from main import main

if __name__ == "__main__":
    main()
