#!/usr/bin/env python3
"""
side_touch_test.py — los diagnose-tool: detecteert "vinger raakt tafel" in het
iPhone side-view, met de BEWEZEN is_touching_side() + de touch-zone uit
calibration_dual.json. Raakt hand_mouse.py niet aan.

Doel (stap 2 van "van pinch naar touchscreen"): visueel bevestigen dat de iPhone
betrouwbaar TOUCH / geen-touch geeft over de hele tafel, vóór we het aan de klik
koppelen. Werkt dit goed, dan integreren we het in een kopie van hand_mouse.py.

⚠️ iPhone Center Stage moet UIT, anders verschuift de tafel-zone per frame.

Gebruik (iPhone-index eerst checken met dual_cam_test.py):
    python side_touch_test.py --idx 2

Bediening: q of ESC = stoppen.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dual_cam_tracker import Calibration, is_touching_side, FINGER_TIPS  # type: ignore

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = HERE / "hand_landmarker.task"
DEFAULT_CALIB = HERE / "calibration_dual.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="iPhone side-view touch-detectie test.")
    ap.add_argument("--idx", type=int, default=2, help="iPhone (side) camera-index.")
    ap.add_argument("--calib", type=Path, default=DEFAULT_CALIB)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    if not args.model.exists():
        print(f"FOUT: model niet gevonden: {args.model}")
        return 1

    calib = Calibration.load(args.calib)
    has_zone = bool(calib.side_zone_bottom)
    print(f"[side_touch_test] touch-zone={'ja' if has_zone else 'nee (val terug op table_y-lijn)'}  "
          f"table_y={calib.table_y_pixel}  thresh={calib.touch_threshold_px}", flush=True)
    if not has_zone and calib.table_y_pixel is None:
        print("WAARSCHUWING: geen touch-zone EN geen table_y in calibration_dual.json. "
              "Draai eerst calibrate_dual.py (touch-zone fase).")

    cap = cv2.VideoCapture(args.idx, cv2.CAP_AVFOUNDATION)
    if not cap.isOpened():
        print(f"FOUT: kan iPhone-index {args.idx} niet openen. Check dual_cam_test.py.")
        return 1
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    base = mp_tasks.BaseOptions(model_asset_path=str(args.model))
    opts = mp_vision.HandLandmarkerOptions(
        base_options=base,
        num_hands=2,
        running_mode=mp_vision.RunningMode.VIDEO,
        min_hand_detection_confidence=0.3,
        min_hand_presence_confidence=0.3,
        min_tracking_confidence=0.3,
    )
    landmarker = mp_vision.HandLandmarker.create_from_options(opts)

    win = "side_touch_test (iPhone)  —  q=stop"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    zone_cache: dict = {}
    ts = 0
    idx_tip = FINGER_TIPS["index"]
    print("[side_touch_test] draait. Leg een vinger op de tafel = groen; in de lucht = rood.",
          flush=True)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts += 1
            res = landmarker.detect_for_video(mp_img, ts)

            out = frame.copy()
            # Touch-zone tekenen: bottom = groen, top = oranje, table_y = rode lijn.
            if calib.side_zone_bottom:
                cv2.polylines(out, [np.array(calib.side_zone_bottom, np.int32).reshape(-1, 1, 2)],
                              True, (0, 220, 0), 2)
            if calib.side_zone_top:
                cv2.polylines(out, [np.array(calib.side_zone_top, np.int32).reshape(-1, 1, 2)],
                              True, (0, 165, 255), 2)
            if calib.table_y_pixel is not None:
                cv2.line(out, (0, calib.table_y_pixel), (w, calib.table_y_pixel), (0, 0, 255), 1)

            index_touch = False
            n_touch = 0
            if res and res.hand_landmarks:
                for hand in res.hand_landmarks:
                    for name, li in FINGER_TIPS.items():
                        if li >= len(hand):
                            continue
                        px, py = hand[li].x * w, hand[li].y * h
                        touch = is_touching_side(
                            px, py, calib.table_y_pixel, calib.touch_threshold_px,
                            side_zone_bottom=calib.side_zone_bottom,
                            side_zone_top=calib.side_zone_top,
                            _zone_cache=zone_cache,
                        )
                        col = (0, 255, 0) if touch else (60, 60, 255)
                        cv2.circle(out, (int(px), int(py)), 9, col, -1)
                        if touch:
                            n_touch += 1
                        if li == idx_tip and touch:
                            index_touch = True

            label = "TOUCH (wijsvinger)" if index_touch else "geen touch"
            col = (0, 255, 0) if index_touch else (60, 60, 255)
            cv2.putText(out, label, (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.4, col, 3, cv2.LINE_AA)
            cv2.putText(out, f"vingers die tafel raken: {n_touch}", (20, 95),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (230, 230, 230), 2, cv2.LINE_AA)
            cv2.putText(out, "groen=raakt tafel   rood=in de lucht   q/ESC=stop",
                        (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (210, 210, 210), 1, cv2.LINE_AA)
            cv2.imshow(win, out)
            k = cv2.waitKey(1) & 0xFF
            if k in (ord("q"), 27):
                break
    finally:
        cap.release()
        landmarker.close()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
