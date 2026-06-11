# -*- coding: utf-8 -*-
r"""
Calibration / sanity-check tool for HP reading.

Runs the main in-game detector over a folder of frames, estimates HP for the
player (green) and enemies (red) with hp_estimator, and writes an annotated copy
of each frame (boxes + HP%) so you can VISUALLY verify and tune the thresholds.

Usage (project root, venv active):
    py hp_debug.py --dir "debug_frames\wall_vision" --out "debug_frames\hp_check"
    py hp_debug.py --dir frames --full-bar 1.1     # tweak reference bar width

If a FULL-HP entity does not read ~100%, adjust --full-bar (lower => higher %).
If bars aren't found, widen HSV ranges in hp_estimator.TEAM_RANGES or raise
--search-above. Once happy, copy good values into cfg/bot_config.toml ->
hp_estimator_cfg (e.g. full_bar_width_frac).
"""
import argparse
import os
import sys

IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="Folder with frames to check.")
    ap.add_argument("--out", default=None, help="Output folder (default: <dir>/hp_check).")
    ap.add_argument("--model", default=os.path.join("models", "mainInGameModel.onnx"))
    ap.add_argument("--conf", type=float, default=0.5)
    ap.add_argument("--full-bar", type=float, default=None,
                    help="Override full_bar_width_frac for quick tuning.")
    ap.add_argument("--search-above", type=float, default=None,
                    help="Override bar_search_above (box-heights above the box).")
    ap.add_argument("--limit", type=int, default=0, help="Max frames to process (0 = all).")
    args = ap.parse_args()

    import cv2
    from detect import Detect
    from vision import hp_estimator as HP

    if not os.path.isdir(args.dir):
        print("ERROR: folder not found: " + args.dir)
        sys.exit(1)
    if not os.path.exists(args.model):
        print("ERROR: main model not found: " + args.model)
        sys.exit(1)

    out_dir = args.out or os.path.join(args.dir, "hp_check")
    os.makedirs(out_dir, exist_ok=True)

    cfg = {}
    if args.full_bar is not None:
        cfg["full_bar_width_frac"] = args.full_bar
    if args.search_above is not None:
        cfg["bar_search_above"] = args.search_above

    det = Detect(args.model, classes=["enemy", "teammate", "player"])
    TEAM = {"player": "self", "teammate": "teammate", "enemy": "enemy"}
    COLOR = {"player": (0, 255, 0), "teammate": (255, 255, 0), "enemy": (0, 0, 255)}  # BGR

    images = sorted(f for f in os.listdir(args.dir) if f.lower().endswith(IMG_EXT))
    if args.limit:
        images = images[:args.limit]
    if not images:
        print("No images in " + args.dir)
        sys.exit(1)

    processed = found = 0
    for name in images:
        bgr = cv2.imread(os.path.join(args.dir, name))
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        results = det.detect_objects(rgb, conf_tresh=args.conf) or {}
        vis = bgr.copy()
        for cls, boxes in results.items():
            team = TEAM.get(cls)
            col = COLOR.get(cls, (255, 255, 255))
            for b in boxes:
                x1, y1, x2, y2 = HP._norm(b)
                cv2.rectangle(vis, (x1, y1), (x2, y2), col, 2)
                hp = None
                if team:
                    hp, info = HP.estimate_hp_fraction(rgb, b, team, cfg=cfg, debug=True)
                    bx = info.get("bar_x")
                    br = info.get("band_rows")
                    if bx and br:
                        cv2.rectangle(vis, (bx[0], br[0]), (bx[1], br[1]), col, 1)
                label = ("%d%%" % int(round(hp * 100))) if hp is not None else "?"
                cv2.putText(vis, cls + " " + label, (x1, max(12, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
                if hp is not None:
                    found += 1
        cv2.imwrite(os.path.join(out_dir, name), vis)
        processed += 1

    print("Processed %d frames, %d HP reads. Annotated frames in: %s" % (processed, found, out_dir))
    print("Tune --full-bar so a full-HP entity reads ~100%, then set hp_estimator_cfg in bot_config.toml.")


if __name__ == "__main__":
    main()
