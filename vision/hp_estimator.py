# -*- coding: utf-8 -*-
r"""
Best-effort HP reading from Brawl Stars health bars (no ML model needed).

Method (robust to dark scenery): a brawler's health bar floats just above its
body. We detect the FILLED (colored) part of the bar -- own/teammate = green,
enemy = red -- measure its width, and divide by a reference full-bar width that
scales with the body box width:

    hp_fraction = filled_bar_width / (box_width * full_bar_width_frac)

Why not detect the empty/dark part? Because dark scenery next to a brawler is
easily confused with a depleted bar. Measuring only the bright colored fill is
far more reliable; the single `full_bar_width_frac` knob calibrates it (a
full-HP entity should read ~1.0). Tune it with hp_debug.py on real frames.

FAIL-SAFE: when no colored bar is found it returns None, and the caller keeps
its default behavior. Pass team = "self" | "teammate" | "enemy".
"""
import numpy as np
import cv2

# Filled-bar HSV ranges (OpenCV H is 0..179). One or more ranges per team.
TEAM_RANGES = {
    "self":     [((35, 70, 80), (90, 255, 255))],                                  # green
    "teammate": [((35, 70, 80), (90, 255, 255))],                                  # green-ish
    "enemy":    [((0, 90, 80), (12, 255, 255)), ((168, 90, 80), (179, 255, 255))], # red (wraps hue)
}

DEFAULTS = {
    "bar_search_above": 1.20,    # search up to N box-heights above the box top
    "bar_search_below": 0.20,    # ...and a little into the box from its top
    "bar_width_pad": 0.60,       # horizontal padding each side, fraction of box width
    "full_bar_width_frac": 1.0,  # reference full-bar width = box_width * this
    "min_filled_cols": 4,        # ignore colored runs narrower than this (px)
    "gap_tol": 4,                # allowed horizontal gap (px) inside the filled run
    "band_frac": 0.12,           # half-height of the row band, fraction of box height
}


def _norm(box):
    x1, y1, x2, y2 = box[:4]
    return int(min(x1, x2)), int(min(y1, y2)), int(max(x1, x2)), int(max(y1, y2))


def filled_span(filled_cols, gap_tol):
    """Pure helper. filled_cols: boolean array over an x range.
    Returns (left, right) of the contiguous filled run starting at the first
    filled column (small gaps <= gap_tol are bridged), or None."""
    n = len(filled_cols)
    left = None
    for c in range(n):
        if filled_cols[c]:
            left = c
            break
    if left is None:
        return None
    right = left
    gap = 0
    for c in range(left, n):
        if filled_cols[c]:
            right = c
            gap = 0
        else:
            gap += 1
            if gap > gap_tol:
                break
    return left, right


def estimate_hp_fraction(frame_rgb, box, team, scale_factor=1.0, cfg=None, debug=False):
    """Return HP fraction in [0,1], or None if no colored bar could be read.
    If debug=True, returns (frac_or_None, info_dict)."""
    c = dict(DEFAULTS)
    if cfg:
        c.update(cfg)
    info = {}
    if frame_rgb is None or box is None:
        return (None, info) if debug else None
    ranges = TEAM_RANGES.get(team)
    if not ranges:
        return (None, info) if debug else None

    H, W = frame_rgb.shape[:2]
    x1, y1, x2, y2 = _norm(box)
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    pad = int(bw * c["bar_width_pad"])
    rx1 = max(0, x1 - pad)
    rx2 = min(W, x2 + pad)
    ry1 = max(0, int(y1 - bh * c["bar_search_above"]))
    ry2 = min(H, int(y1 + bh * c["bar_search_below"]))
    info["roi"] = (rx1, ry1, rx2, ry2)
    if (rx2 - rx1) < c["min_filled_cols"] or (ry2 - ry1) < 2:
        return (None, info) if debug else None

    roi = frame_rgb[ry1:ry2, rx1:rx2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
    filled = np.zeros(roi.shape[:2], dtype=np.uint8)
    for lo, hi in ranges:
        filled |= cv2.inRange(hsv, np.array(lo, dtype=np.uint8), np.array(hi, dtype=np.uint8))

    row_filled = (filled > 0).sum(axis=1)
    if int(row_filled.max()) < c["min_filled_cols"]:
        return (None, info) if debug else None
    best = int(np.argmax(row_filled))
    band = max(1, int(bh * c["band_frac"]))
    r0 = max(0, best - band)
    r1 = min(roi.shape[0], best + band + 1)

    band_filled = (filled[r0:r1] > 0).sum(axis=0) > 0
    span = filled_span(band_filled, c["gap_tol"])
    if span is None:
        return (None, info) if debug else None
    left, right = span
    filled_w = right - left + 1
    if filled_w < c["min_filled_cols"]:
        return (None, info) if debug else None

    ref = max(1.0, bw * c["full_bar_width_frac"])
    frac = max(0.0, min(1.0, filled_w / ref))
    info.update({"frac": frac, "filled_w": filled_w, "ref": ref,
                 "bar_x": (rx1 + left, rx1 + right),
                 "band_rows": (ry1 + r0, ry1 + r1)})
    return (frac, info) if debug else frac


def estimate_hp(frame_rgb, box, team, scale_factor=1.0, cfg=None):
    """Convenience wrapper -> float in [0,1] or None."""
    return estimate_hp_fraction(frame_rgb, box, team, scale_factor=scale_factor, cfg=cfg, debug=False)
