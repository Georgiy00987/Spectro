# -*- coding: utf-8 -*-
"""
Wall detector viewer for Spectro (headless-OpenCV friendly).

Shows, in real time, the rectangles the WALL neural network detects, so you can
SEE exactly what the bot thinks is a wall / bush.

It does NOT play the game and does NOT press any keys - it only watches.

The window is drawn with Tkinter (built into Python). cv2.imshow is NOT used,
so this works even when only opencv-python-headless is installed.

Put this file next to play.py and run:
    py wall_viewer.py

Colors:
    RED        = wall          (raw detection from the neural net)
    ORANGE     = close_bush    (raw detection)
    GREEN      = bush          (raw detection, does NOT block the bot)
    MAGENTA    = the merged walls the bot ACTUALLY uses to block movement

Keys (the window must have focus):
    q  - quit
    m  - toggle the magenta bot-walls overlay
    b  - toggle bush boxes
    [  - lower confidence (shows MORE boxes)
    ]  - raise confidence (shows FEWER boxes)
"""

import os
import sys
import base64
import tkinter as tk

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from play import Play
from window_controller import WindowController

MAIN_MODEL = os.path.join("models", "mainInGameModel.onnx")
TILE_MODEL = os.path.join("models", "tileDetector.onnx")

# BGR colors (cv2 draws in BGR; cv2.imencode also expects BGR).
RAW_COLORS = {
    "wall": (0, 0, 255),         # red
    "close_bush": (0, 165, 255), # orange
    "bush": (0, 200, 0),         # green
}
MERGED_COLOR = (255, 0, 255)     # magenta - what actually blocks the bot

DISPLAY_SCALE = 0.7


class WallViewer:
    def __init__(self):
        self.controller = WindowController()
        self.play = Play(MAIN_MODEL, TILE_MODEL, self.controller)
        self.show_merged = True
        self.show_bush = True
        self.running = True
        self.last_frame_id = -1

        self.root = tk.Tk()
        self.root.title("Wall Detector")
        self.label = tk.Label(self.root)
        self.label.pack()
        self.root.bind("<Key>", self.on_key)
        self.root.protocol("WM_DELETE_WINDOW", self.stop)
        self._photo = None

        print("Wall viewer running. Focus the window and press 'q' to quit.")
        print("Current wall confidence:", self.play.wall_detection_confidence)

    def stop(self):
        self.running = False

    def on_key(self, event):
        ch = (event.char or "").lower()
        if ch == "q":
            self.stop()
        elif ch == "m":
            self.show_merged = not self.show_merged
        elif ch == "b":
            self.show_bush = not self.show_bush
        elif ch == "[":
            self.play.wall_detection_confidence = max(0.05, round(self.play.wall_detection_confidence - 0.05, 2))
            print("conf =", self.play.wall_detection_confidence)
        elif ch == "]":
            self.play.wall_detection_confidence = min(0.95, round(self.play.wall_detection_confidence + 0.05, 2))
            print("conf =", self.play.wall_detection_confidence)

    def render_frame(self):
        frame = self.controller.screenshot()  # RGB
        if frame is None:
            return None

        try:
            frame_id = self.controller.get_latest_frame_id()
            if frame_id == self.last_frame_id:
                return False  # nothing new
            self.last_frame_id = frame_id
        except Exception:
            pass

        raw = self.play.get_tile_data(frame)         # {class: [[x1,y1,x2,y2], ...]}
        merged = self.play.process_tile_data(raw)    # list of [x1,y1,x2,y2] the bot uses

        img = cv2.cvtColor(np.asarray(frame), cv2.COLOR_RGB2BGR)

        counts = {}
        for cls, boxes in raw.items():
            counts[cls] = len(boxes)
            if cls == "bush" and not self.show_bush:
                continue
            color = RAW_COLORS.get(cls, (200, 200, 200))
            for b in boxes:
                x1, y1, x2, y2 = map(int, b[:4])
                cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
                cv2.putText(img, cls, (x1, max(y1 - 5, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

        if self.show_merged:
            for b in merged:
                x1, y1, x2, y2 = map(int, b[:4])
                cv2.rectangle(img, (x1, y1), (x2, y2), MERGED_COLOR, 3)

        info = "conf=%.2f  wall=%d  close_bush=%d  bush=%d  bot_walls=%d" % (
            self.play.wall_detection_confidence,
            counts.get("wall", 0),
            counts.get("close_bush", 0),
            counts.get("bush", 0),
            len(merged),
        )
        cv2.rectangle(img, (0, 0), (img.shape[1], 30), (0, 0, 0), -1)
        cv2.putText(img, info, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(img, "[ ] = confidence   m = bot walls   b = bush   q = quit",
                    (8, img.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (0, 255, 255), 1, cv2.LINE_AA)

        if DISPLAY_SCALE < 0.999:
            img = cv2.resize(img, None, fx=DISPLAY_SCALE, fy=DISPLAY_SCALE,
                             interpolation=cv2.INTER_AREA)
        return img

    def show(self, img):
        # Encode to PNG (works in headless OpenCV) and hand it to Tkinter.
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            return
        data = base64.b64encode(buf.tobytes())
        self._photo = tk.PhotoImage(data=data)
        self.label.configure(image=self._photo)

    def tick(self):
        if not self.running:
            self.root.destroy()
            return
        try:
            img = self.render_frame()
            if isinstance(img, np.ndarray):
                self.show(img)
        except Exception as exc:
            print("render error:", exc)
        self.root.after(15, self.tick)

    def run(self):
        self.root.after(0, self.tick)
        try:
            self.root.mainloop()
        finally:
            try:
                self.controller.close()
            except Exception:
                pass


def main():
    WallViewer().run()


if __name__ == "__main__":
    main()
