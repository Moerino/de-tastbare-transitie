#!/usr/bin/env python3
"""
calibrate_side_screen.py — iPhone side-cam → scherm homografie (sensor-fusie).

Waarom: de DJI kijkt schuin op de tafel. Langs zijn diepte-as (near-far op de
tafel) is een paar pixels al een grote sprong → onnauwkeurig. De iPhone kijkt
juist dwars op die as en meet hem heel precies. Met deze kalibratie kan de
tracker in --fusion modus screen-X van de iPhone nemen en screen-Y van de DJI.

Hoe: projecteert een 3×3 raster van stippen op het beamer-scherm. Per stip raak
je met je WIJSVINGER aan en houd je ~2.5 sec vast. De iPhone-fingertip-positie
wordt gemiddeld en gekoppeld aan de bekende schermpositie. Na 9 punten:
cv2.findHomography(iphone_pixels → screen_pixels). Opgeslagen als
`side_homography` in calibration_dual.json.

Vereist: een bestaande calibration_dual.json met de side-zone (touch-detectie),
zodat we weten WANNEER de vinger de tafel raakt.

Gebruik:
  cd "/.../tracking/hand_mouse" && ../dji_tracker/.venv/bin/python \
     calibrate_side_screen.py --side-idx 2 --display-idx 1 --hold-secs 2.5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import hand_mouse as hm
# Hergebruik bewezen helpers uit de bestaande fine-tune tool.
from fine_tune_calibration import (
    open_cam, make_landmarker, detect_index_tip,
    render_dot_with_progress, make_grid, open_overlay,
)
from dual_cam_tracker import Calibration, is_touching_side

log = logging.getLogger("calibrate_side_screen")

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = HERE / "hand_landmarker.task"
DEFAULT_CALIB = HERE / "calibration_dual.json"


def capture_side_dot(side_cap, side_lm, calib, display, win,
                     sx: int, sy: int, dot_num: int, total: int,
                     hold_secs: float) -> tuple[float, float] | None:
    """Wacht tot de iPhone-vinger de tafel raakt en houd vast; geef gemiddelde
    iPhone-fingertip-pixel terug. None bij ESC."""
    samples: list[tuple[float, float]] = []
    hold_started: float | None = None
    zone_cache: dict = {}

    while True:
        ok, frame = side_cap.read()
        if not ok:
            continue
        ts_ms = int(time.monotonic() * 1000)
        tip = detect_index_tip(side_lm, frame, ts_ms)

        touching = False
        if tip is not None:
            touching = is_touching_side(
                tip[0], tip[1], calib.table_y_pixel, calib.touch_threshold_px,
                side_zone_bottom=calib.side_zone_bottom,
                side_zone_top=calib.side_zone_top,
                _zone_cache=zone_cache,
            )

        progress = 0.0
        phase = "wachten"
        instruction = "tik en houd vast op de stip"
        if touching and tip is not None:
            if hold_started is None:
                hold_started = time.monotonic()
                samples = []
            samples.append(tip)
            elapsed = time.monotonic() - hold_started
            progress = min(1.0, elapsed / hold_secs)
            phase = "houden"
            instruction = f"HOUD VAST ({max(0.0, hold_secs - elapsed):.1f}s)"
            if progress >= 1.0 and len(samples) >= 8:
                arr = np.array(samples[-30:])
                return float(np.median(arr[:, 0])), float(np.median(arr[:, 1]))
        else:
            hold_started = None
            samples = []
            if tip is None:
                instruction = "iPhone ziet je vinger niet"
            elif not touching:
                instruction = "raak de tafel aan op de stip"

        img = render_dot_with_progress(display, sx, sy, progress, instruction,
                                        dot_num, total, phase)
        cv2.imshow(win, img)
        if (cv2.waitKey(20) & 0xFF) == 27:
            return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Kalibreer de iPhone side-cam → scherm mapping (sensor-fusie).")
    parser.add_argument("--side-idx", type=int, default=2)
    parser.add_argument("--display-idx", type=int, default=None)
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument("--cols", type=int, default=3)
    parser.add_argument("--hold-secs", type=float, default=2.5)
    parser.add_argument("--calib", type=Path, default=DEFAULT_CALIB)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.calib.exists():
        log.error("Geen calibration_dual.json — eerst calibrate_dual.py draaien "
                  "(voor de side-zone touch-detectie).")
        return 1

    calib = Calibration.load(args.calib)
    if calib.side_zone_bottom is None and calib.table_y_pixel is None:
        log.error("Side-zone/tafel ontbreekt in de kalibratie. Draai eerst "
                  "calibrate_dual.py (Fase B + C).")
        return 1

    displays = hm.list_displays()
    display_idx = args.display_idx
    if display_idx is None:
        for i, d in enumerate(displays):
            if not d.get("main"):
                display_idx = i
                break
    display = hm.pick_display(displays, display_idx)
    log.info("Projectie op scherm #%s: %dx%d @ (%d,%d)",
             display_idx, display["w"], display["h"], display["x"], display["y"])

    side_cap = open_cam(args.side_idx, "side-iPhone")
    if side_cap is None:
        return 1
    side_lm = make_landmarker(args.model)

    win = open_overlay(display)
    dots = make_grid(display, args.rows, args.cols)
    total = len(dots)

    # Countdown
    for sec in range(3, 0, -1):
        img = np.zeros((display["h"], display["w"], 3), dtype=np.uint8)
        cv2.putText(img, f"iPhone-kalibratie start over {sec}…",
                    (display["w"] // 2 - 320, display["h"] // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3, cv2.LINE_AA)
        cv2.imshow(win, img)
        cv2.waitKey(1000)

    side_pts: list[tuple[float, float]] = []
    screen_pts: list[tuple[int, int]] = []
    try:
        for i, (sx, sy) in enumerate(dots, start=1):
            res = capture_side_dot(side_cap, side_lm, calib, display, win,
                                   sx, sy, i, total, args.hold_secs)
            if res is None:
                log.warning("Geannuleerd op stip %d/%d", i, total)
                return 1
            side_pts.append(res)
            screen_pts.append((sx, sy))
            log.info("[%d/%d] scherm=(%d,%d)  iPhone-cam=(%.1f,%.1f)",
                     i, total, sx, sy, res[0], res[1])
            # ✓-flits
            img = np.zeros((display["h"], display["w"], 3), dtype=np.uint8)
            cv2.circle(img, (sx, sy), 50, (50, 230, 50), -1, cv2.LINE_AA)
            cv2.imshow(win, img)
            cv2.waitKey(350)
    finally:
        side_cap.release()
        side_lm.close()
        cv2.destroyAllWindows()

    if len(side_pts) < 4:
        log.error("Te weinig metingen (%d < 4) voor homografie.", len(side_pts))
        return 1

    H, mask = cv2.findHomography(
        np.array(side_pts, dtype=np.float32),
        np.array(screen_pts, dtype=np.float32),
        method=cv2.RANSAC, ransacReprojThreshold=25.0)
    if H is None:
        log.error("Homografie-berekening faalde.")
        return 1
    inliers = int(mask.sum()) if mask is not None else len(side_pts)
    log.info("iPhone→scherm homografie OK met %d/%d inliers", inliers, len(side_pts))

    data = json.loads(args.calib.read_text())
    data["side_homography"] = H.tolist()
    data["side_homography_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    args.calib.write_text(json.dumps(data, indent=2))
    log.info("✓ side_homography opgeslagen in %s", args.calib)
    log.info("Start de tracker nu met --fusion om iPhone-X + DJI-Y te gebruiken.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
