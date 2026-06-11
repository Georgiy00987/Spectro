# -*- coding: utf-8 -*-
"""
Imitation-learning data collector for Spectro.

WHAT IT DOES
  While YOU play manually (the bot does NOT control anything), this records,
  for every new game frame:
    * what the models see  -> player / enemies / teammates / walls
    * what YOU did          -> WASD movement keys, attack/super/gadget keys,
                              and mouse position + buttons (for aim/attack)
  Rows are appended to  datasets/imitation/session_<timestamp>.jsonl

HOW TO USE
  1. Start LDPlayer + Brawl Stars exactly like you do for the bot.
  2. From the PROJECT ROOT (next to play.py / main.py), with the venv active:
         py collect_imitation_data.py
  3. Play normally for ~20-30 minutes (or more). Play the way you want the
     bot to play: position well, don't stand AFK, don't troll.
  4. Press Ctrl+C in the console (or close it) to stop. The file is saved.

NOTES
  * The bot is OFF here on purpose - this only reads your input, never sends any.
  * Run it as many times as you like; each run makes a new session file.
  * Windows only (uses the Win32 API to read your keyboard/mouse globally).
"""

import os
import sys
import json
import time
import ctypes
import datetime

# ----------------------------------------------------------------------------
# Config - adjust the attack/super/gadget keys to YOUR LDPlayer key mapping.
# Movement is assumed to be W A S D. If your attack is the mouse, that is
# captured automatically (left/right button + cursor position).
# ----------------------------------------------------------------------------
MOVE_KEYS = ["w", "a", "s", "d"]
# Extra keys to record the on/off state of every frame. Add whatever LDPlayer
# keys you use for attack / super / gadget / gadget2 etc. (single chars or the
# named keys in VK_NAMED below). Unknown bindings? Leave a broad set here and we
# will figure out which one is "attack" from the data later.
EXTRA_KEYS = ["space", "e", "q", "f", "r", "shift", "ctrl", "1", "2", "3"]
SAVE_FRAMES = False  # set True to also dump jpg frames (big!) for re-labeling
OUTPUT_DIR = os.path.join("datasets", "imitation")

# ----------------------------------------------------------------------------
# Win32 input reading (no external deps)
# ----------------------------------------------------------------------------
if os.name != "nt":
    print("This collector must run on Windows (it reads global keyboard/mouse)." )
    # Do not hard-exit on import for py_compile checks; only exit when run.

_user32 = ctypes.windll.user32 if os.name == "nt" else None

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_NAMED = {
    "space": 0x20,
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12,
    "tab": 0x09,
    "enter": 0x0D,
    "esc": 0x1B,
}


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _vk_for(key):
    key = key.lower()
    if key in VK_NAMED:
        return VK_NAMED[key]
    if len(key) == 1:
        return ord(key.upper())
    return None


def _is_down(vk):
    if vk is None or _user32 is None:
        return 0
    # High-order bit set => key is currently down.
    return 1 if (_user32.GetAsyncKeyState(vk) & 0x8000) else 0


def _cursor_pos():
    if _user32 is None:
        return (0, 0)
    pt = _Point()
    _user32.GetCursorPos(ctypes.byref(pt))
    return (int(pt.x), int(pt.y))


def _centers(boxes):
    """Convert [x1,y1,x2,y2] boxes to [cx, cy] centers."""
    out = []
    for b in boxes or []:
        if len(b) >= 4:
            x1, y1, x2, y2 = b[0], b[1], b[2], b[3]
            out.append([int((x1 + x2) / 2), int((y1 + y2) / 2)])
    return out


def _boxes_xywh(boxes):
    """Convert [x1,y1,x2,y2] to [cx,cy,w,h] for compact wall storage."""
    out = []
    for b in boxes or []:
        if len(b) >= 4:
            x1, y1, x2, y2 = b[0], b[1], b[2], b[3]
            out.append([
                int((x1 + x2) / 2), int((y1 + y2) / 2),
                int(abs(x2 - x1)), int(abs(y2 - y1)),
            ])
    return out


def main():
    if os.name != "nt":
        print("Exiting: Windows is required.")
        sys.exit(1)

    # Imported here so the file still py_compiles on non-Windows machines.
    import cv2  # noqa: F401  (only needed when SAVE_FRAMES is True)
    from window_controller import WindowController
    from play import Play

    main_model = os.path.join(".", "models", "mainInGameModel.onnx")
    tile_model = os.path.join(".", "models", "tileDetector.onnx")

    print("Starting capture stack (this connects to the emulator like the bot)...")
    try:
        wc = WindowController()
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to start WindowController: {exc}")
        print("Make sure LDPlayer + Brawl Stars are running, like for the bot.")
        sys.exit(1)

    try:
        play = Play(main_model, tile_model, wc)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to load detection models: {exc}")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(OUTPUT_DIR, f"session_{stamp}.jsonl")
    frames_dir = os.path.join(OUTPUT_DIR, f"frames_{stamp}")
    if SAVE_FRAMES:
        os.makedirs(frames_dir, exist_ok=True)

    extra_vks = [(k, _vk_for(k)) for k in EXTRA_KEYS]
    move_vks = [(k, _vk_for(k)) for k in MOVE_KEYS]

    print(f"Recording to: {out_path}")
    print("Play normally. Press Ctrl+C here to stop.")

    last_frame_id = -1
    rows = 0
    started = time.time()
    out = open(out_path, "w", encoding="utf-8")

    # Write a small header line describing the schema/config.
    header = {
        "_meta": True,
        "created": stamp,
        "move_keys": MOVE_KEYS,
        "extra_keys": EXTRA_KEYS,
        "note": "coords are in full game-frame pixels; angle 0=right,90=down,180=left,270=up",
    }
    out.write(json.dumps(header) + "\n")
    out.flush()

    try:
        while True:
            frame_id = wc.get_latest_frame_id()
            if frame_id == last_frame_id:
                time.sleep(0.005)
                continue
            last_frame_id = frame_id

            try:
                frame = wc.screenshot()
            except Exception:  # noqa: BLE001
                # Feed hiccup; skip this tick.
                time.sleep(0.02)
                continue
            if frame is None:
                time.sleep(0.02)
                continue

            h, w = frame.shape[:2]

            # --- detections (same pipeline the bot uses) ---
            try:
                main_data = play.get_main_data(frame)
            except Exception:  # noqa: BLE001
                main_data = {}
            try:
                tile_data = play.get_tile_data(frame)
            except Exception:  # noqa: BLE001
                tile_data = {}

            players = _centers(main_data.get("player"))
            enemies = _centers(main_data.get("enemy"))
            teammates = _centers(main_data.get("teammate"))
            walls = {cls: _boxes_xywh(boxes) for cls, boxes in (tile_data or {}).items()}

            # --- your input this frame ---
            move_state = {k: _is_down(vk) for k, vk in move_vks}
            extra_state = {k: _is_down(vk) for k, vk in extra_vks}
            mx, my = _cursor_pos()
            mouse = {
                "x": mx,
                "y": my,
                "left": _is_down(VK_LBUTTON),
                "right": _is_down(VK_RBUTTON),
            }
            move_combo = "".join(k for k in MOVE_KEYS if move_state.get(k))

            row = {
                "t": round(time.time() - started, 3),
                "frame_id": frame_id,
                "w": w,
                "h": h,
                "player": players[0] if players else None,
                "enemies": enemies,
                "teammates": teammates,
                "walls": walls,
                "move": move_state,
                "move_combo": move_combo,
                "keys": extra_state,
                "mouse": mouse,
            }
            out.write(json.dumps(row) + "\n")
            rows += 1

            if SAVE_FRAMES:
                try:
                    cv2.imwrite(os.path.join(frames_dir, f"{frame_id}.jpg"), frame,
                                [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                except Exception:  # noqa: BLE001
                    pass

            if rows % 200 == 0:
                elapsed = time.time() - started
                out.flush()
                print(f"  {rows} frames recorded ({elapsed/60:.1f} min)...")
    except KeyboardInterrupt:
        print("\nStopping (Ctrl+C).")
    finally:
        out.flush()
        out.close()
        try:
            wc.keys_up(list("wasd"))
        except Exception:  # noqa: BLE001
            pass
        try:
            wc.close()
        except Exception:  # noqa: BLE001
            pass
        mins = (time.time() - started) / 60
        print(f"Saved {rows} frames over {mins:.1f} min to {out_path}")


if __name__ == "__main__":
    main()
