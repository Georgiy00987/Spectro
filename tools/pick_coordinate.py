"""Click on a screenshot to print game coordinates.

Usage:
    python tools/pick_coordinate.py "C:\path\to\screenshot.png"

Left click prints the clicked coordinate in original image pixels and scaled to
1920x1080 coordinates. Use the 1920x1080 value in cfg/lobby_config.toml.
"""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk


def main():
    if len(sys.argv) < 2:
        print('Usage: python tools/pick_coordinate.py "C:\\path\\to\\screenshot.png"')
        raise SystemExit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        raise SystemExit(1)

    image = Image.open(path).convert("RGB")
    w, h = image.size
    print(f"Image: {path}")
    print(f"Size: {w}x{h}")
    print("Click the Play Again button. Use the 1920x1080 coordinate printed below.")

    root = tk.Tk()
    root.title("Pick coordinate - click Play Again button")

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    max_w = int(screen_w * 0.9)
    max_h = int(screen_h * 0.85)
    scale = min(max_w / w, max_h / h, 1.0)
    display_w = max(1, int(w * scale))
    display_h = max(1, int(h * scale))

    display_image = image.resize((display_w, display_h), Image.Resampling.LANCZOS)
    tk_image = ImageTk.PhotoImage(display_image)

    info = tk.Label(
        root,
        text="Click center of Play Again. Coordinates will be printed in console.",
        font=("Arial", 11),
    )
    info.pack(padx=8, pady=(8, 4))

    canvas = tk.Canvas(root, width=display_w, height=display_h, highlightthickness=0)
    canvas.pack(padx=8, pady=8)
    canvas.create_image(0, 0, anchor="nw", image=tk_image)

    result_var = tk.StringVar(value="Waiting for click...")
    result_label = tk.Label(root, textvariable=result_var, font=("Consolas", 10), justify="left")
    result_label.pack(padx=8, pady=(0, 8))

    def on_click(event):
        x = round(event.x / scale)
        y = round(event.y / scale)
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))
        game_x = round(x * 1920 / w)
        game_y = round(y * 1080 / h)
        text = (
            f"clicked image={x},{y}  1920x1080={game_x},{game_y}\n"
            "Put this into cfg/lobby_config.toml:\n"
            f"play_again_x = {game_x}\n"
            f"play_again_y = {game_y}"
        )
        print(text)
        result_var.set(text)
        r = 6
        canvas.delete("marker")
        canvas.create_oval(event.x - r, event.y - r, event.x + r, event.y + r, outline="red", width=3, tags="marker")
        canvas.create_line(event.x - 12, event.y, event.x + 12, event.y, fill="red", width=2, tags="marker")
        canvas.create_line(event.x, event.y - 12, event.x, event.y + 12, fill="red", width=2, tags="marker")

    canvas.bind("<Button-1>", on_click)
    root.bind("<Escape>", lambda _e: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    main()
