from __future__ import annotations

import sys
from pathlib import Path


def set_windows_app_id(app_id: str = "Spectro.Bot") -> bool:
    """Set Windows AppUserModelID before creating a Tk window.

    This helps Windows use the Tk window icon for taskbar grouping instead of
    showing a generic python.exe icon. It is harmless on non-Windows systems.
    """
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(str(app_id))
        return True
    except Exception:
        return False


def find_icon_path(icon_name: str = "icon.ico") -> Path | None:
    """Return the best existing path for the application icon.

    The GUI can be launched from different working directories, so a plain
    "icon.ico" is fragile. This helper checks the current directory, the
    project root and, if present, PyInstaller's temporary folder.
    """
    candidates = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / icon_name)

    candidates.extend([
        Path.cwd() / icon_name,
        Path(__file__).resolve().parents[1] / icon_name,
        Path(sys.argv[0]).resolve().parent / icon_name if sys.argv and sys.argv[0] else None,
    ])

    seen = set()
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            candidate = candidate.resolve()
        except OSError:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def set_window_icon(window, icon_name: str = "icon.ico") -> Path | None:
    """Set a Tk/CustomTkinter window icon without depending on cwd.

    Uses both iconbitmap and iconphoto. iconbitmap is the native Windows path
    for .ico files, while iconphoto can improve Alt+Tab/taskbar behavior for
    Tk windows. All failures are ignored so missing/corrupt icon files do not
    crash the application.
    """
    icon_path = find_icon_path(icon_name)
    if icon_path is None:
        return None

    try:
        window.iconbitmap(default=str(icon_path))
    except Exception:
        try:
            window.iconbitmap(str(icon_path))
        except Exception:
            pass

    try:
        from PIL import Image, ImageTk

        image = Image.open(icon_path)
        photo = ImageTk.PhotoImage(image)
        window.iconphoto(True, photo)
        # Tk keeps only a weak Tcl-side reference. Keep Python reference alive.
        setattr(window, "_spectro_icon_photo", photo)
    except Exception:
        pass

    return icon_path
