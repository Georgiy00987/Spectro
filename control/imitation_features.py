"""Shared feature extraction for the imitation policy.

This module is used BOTH during training (in the sandbox) and at inference
time inside the bot (play.py). Keeping the featurization in one place
guarantees the bot computes exactly the same inputs the model was trained on.

No external deps beyond numpy + stdlib math, so it drops straight into the
bot's venv.

Coordinate convention (matches the bot): angle 0=right, 90=down, 180=left,
270=up; screen y grows downward. All coordinates are full game-frame pixels.
"""
import math

# Bump this whenever the feature layout changes so the bot can refuse to load
# a model trained on an incompatible layout.
FEATURE_VERSION = 1

# 8 movement directions used for the discrete movement head.
# Index 0 of the move head is "idle"; indices 1..8 map to these angles.
DIR_ANGLES = [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]

MAX_ENEMIES_FEAT = 3  # nearest-K enemies encoded individually


def _rel(px, py, tx, ty, diag):
    dx = tx - px
    dy = ty - py
    dist = math.hypot(dx, dy)
    ang = math.atan2(dy, dx)
    return dist / diag, math.cos(ang), math.sin(ang), dist


def _centroid(points):
    n = len(points)
    if n == 0:
        return None
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    return (sx / n, sy / n)


def featurize(player, enemies, teammates, walls, w, h):
    """Build the egocentric feature vector for one frame.

    Returns a list[float] of length FEATURE_DIM, or None if there is no player
    box (in that case the policy should not be used for this frame).

    player: [cx, cy] or None
    enemies / teammates: list of [cx, cy]
    walls: list of [cx, cy, ww, hh]
    w, h: frame width / height in pixels
    """
    if not player:
        return None
    px, py = float(player[0]), float(player[1])
    w = float(w) or 960.0
    h = float(h) or 544.0
    diag = math.hypot(w, h)

    feats = []
    # --- player position (normalized) ---
    feats.append(px / w)
    feats.append(py / h)

    enemies = enemies or []
    teammates = teammates or []
    walls = walls or []

    # --- enemy summary ---
    feats.append(min(len(enemies), 6) / 6.0)
    feats.append(1.0 if enemies else 0.0)

    # nearest-K enemies (sorted by distance)
    enr = []
    for e in enemies:
        nd, c, s, d = _rel(px, py, float(e[0]), float(e[1]), diag)
        enr.append((d, nd, c, s))
    enr.sort(key=lambda t: t[0])
    for i in range(MAX_ENEMIES_FEAT):
        if i < len(enr):
            _, nd, c, s = enr[i]
            feats += [1.0, nd, c, s]
        else:
            feats += [0.0, 0.0, 0.0, 0.0]

    # enemy centroid
    ec = _centroid(enemies)
    if ec:
        nd, c, s, _ = _rel(px, py, ec[0], ec[1], diag)
        feats += [1.0, nd, c, s]
    else:
        feats += [0.0, 0.0, 0.0, 0.0]

    # --- teammate summary ---
    feats.append(min(len(teammates), 6) / 6.0)
    feats.append(1.0 if teammates else 0.0)
    tmr = []
    for t in teammates:
        nd, c, s, d = _rel(px, py, float(t[0]), float(t[1]), diag)
        tmr.append((d, nd, c, s))
    tmr.sort(key=lambda t: t[0])
    if tmr:
        _, nd, c, s = tmr[0]
        feats += [1.0, nd, c, s]
    else:
        feats += [0.0, 0.0, 0.0, 0.0]
    tc = _centroid(teammates)
    if tc:
        nd, c, s, _ = _rel(px, py, tc[0], tc[1], diag)
        feats += [1.0, nd, c, s]
    else:
        feats += [0.0, 0.0, 0.0, 0.0]

    # --- walls: 8-direction closeness + nearest wall ---
    dir_close = [0.0] * 8
    nearest = None
    half = 22.5
    scale = 0.5 * diag
    for wbox in walls:
        wx, wy = float(wbox[0]), float(wbox[1])
        nd, c, s, d = _rel(px, py, wx, wy, diag)
        if nearest is None or d < nearest[0]:
            nearest = (d, nd, c, s)
        ang = math.degrees(math.atan2(wy - py, wx - px)) % 360.0
        idx = int((ang + half) // 45.0) % 8
        close = max(0.0, 1.0 - d / scale)
        if close > dir_close[idx]:
            dir_close[idx] = close
    feats += dir_close
    if nearest:
        feats += [1.0, nearest[1], nearest[2], nearest[3]]
    else:
        feats += [0.0, 0.0, 0.0, 0.0]

    return feats


# Compute the feature dimension once so both sides agree.
def _feature_dim():
    dummy = featurize([100.0, 100.0], [[200.0, 200.0]], [[50.0, 50.0]],
                      [[300.0, 300.0, 20.0, 20.0]], 960, 544)
    return len(dummy)


FEATURE_DIM = _feature_dim()


def move_to_class(move):
    """Map a {w,a,s,d} dict to a movement class 0..8 (0 = idle)."""
    wv = 1 if move.get("w") else 0
    av = 1 if move.get("a") else 0
    sv = 1 if move.get("s") else 0
    dv = 1 if move.get("d") else 0
    dx = dv - av
    dy = sv - wv  # y grows downward, s = down
    if dx == 0 and dy == 0:
        return 0
    ang = math.degrees(math.atan2(dy, dx)) % 360.0
    idx = int((ang + 22.5) // 45.0) % 8
    return idx + 1


def class_to_angle(cls):
    """Movement class 1..8 -> angle in degrees. Class 0 (idle) -> None."""
    if cls <= 0:
        return None
    return DIR_ANGLES[(cls - 1) % 8]


if __name__ == "__main__":
    print("FEATURE_VERSION", FEATURE_VERSION)
    print("FEATURE_DIM", FEATURE_DIM)
    print("DIR_ANGLES", DIR_ANGLES)
