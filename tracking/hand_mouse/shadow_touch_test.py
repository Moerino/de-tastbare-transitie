#!/usr/bin/env python3
"""
shadow_touch_test.py — meet-experiment voor schaduw/spiegel-touch (per vinger).

Idee (Wilson PlayAnywhere + spiegeling op het glanzende scherm): een vinger raakt
het glas pas echt aan als de vingertop en zijn schaduw/spiegeling samenvallen. Bij
zweven zit er een streepje helder scherm (de "gap") tussen; bij contact is die gap
weg.

PER-VINGER ANKERING (lost het matching-probleem op): we detecteren GEEN losse
schaduw-vingers. Voor elke échte vingertop kijken we in een klein patch vlak eronder,
in de richting van zijn eigen schaduw/spiegeling. Zo hoort elke schaduw automatisch
bij de juiste vinger en kun je nooit per ongeluk de schaduw van een andere vinger of
van de hand raken.

  - Patch DONKER (schaduw/spiegeling staat tegen de vinger) -> gap dicht -> TOUCH
  - Patch HELDER (scherm zichtbaar tussen vinger en schaduw) -> gap open -> zweven

De `offset` (afstand vingertop -> meetpatch) is meteen de touch-gevoeligheid.

Gebruik:
    # iPhone (side):  spiegeling zit recht onder de vinger
    python shadow_touch_test.py --view side --idx 2
    # DJI (top):      schaduw ligt onder een hoek -> stel 'hoek' bij met a/f
    python shadow_touch_test.py --view top --idx 0

Live tunen:  w/s = offset,  e/d = patchgrootte,  -/= = drempel,  a/f = zoekhoek,  q/ESC = stop.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = HERE / "hand_landmarker.task"
FINGER_TIPS = {"thumb": 4, "index": 8, "middle": 12, "ring": 16, "pinky": 20}


def _clampi(v, lo, hi):
    return max(lo, min(hi, int(v)))


def patch_mean(gray, cx, cy, half):
    """Gemiddelde helderheid (0-255) van een vierkant patch rond (cx,cy)."""
    h, w = gray.shape
    x0, x1 = _clampi(cx - half, 0, w - 1), _clampi(cx + half, 0, w - 1)
    y0, y1 = _clampi(cy - half, 0, h - 1), _clampi(cy + half, 0, h - 1)
    if x1 <= x0 or y1 <= y0:
        return 255.0
    return float(gray[y0:y1, x0:x1].mean())


def main() -> int:
    ap = argparse.ArgumentParser(description="Schaduw/spiegel touch-detectie experiment (per vinger).")
    ap.add_argument("--view", choices=("side", "top"), default="side",
                    help="side = iPhone (spiegeling recht onder vinger), top = DJI (schaduw onder hoek).")
    ap.add_argument("--idx", type=int, default=None, help="camera-index (default: side=2, top=0).")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--max-hands", type=int, default=2)
    args = ap.parse_args()

    idx = args.idx if args.idx is not None else (2 if args.view == "side" else 0)
    if not args.model.exists():
        print(f"FOUT: model niet gevonden: {args.model}")
        return 1

    cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)
    if not cap.isOpened():
        print(f"FOUT: kan camera-index {idx} niet openen. Check dual_cam_test.py.")
        return 1
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    base = mp_tasks.BaseOptions(model_asset_path=str(args.model))
    opts = mp_vision.HandLandmarkerOptions(
        base_options=base, num_hands=args.max_hands,
        running_mode=mp_vision.RunningMode.VIDEO,
        min_hand_detection_confidence=0.3,
        min_hand_presence_confidence=0.3,
        min_tracking_confidence=0.3,
    )
    landmarker = mp_vision.HandLandmarker.create_from_options(opts)

    # Instelbare parameters (live met toetsen).
    angle = 90.0            # zoekrichting in graden; 90 = recht naar beneden in beeld
    offset = 22             # vingertop -> meetpatch (px) = touch-gevoeligheid
    half = 7                # halve patchgrootte
    thr = 110               # patch < thr = donker = schaduw raakt = TOUCH
    if args.view == "top":
        offset = 28         # schaduw ligt vaak iets verder in het schuine DJI-beeld

    win = f"shadow_touch_test [{args.view}] idx {idx}"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    ts = 0
    idx_tip = FINGER_TIPS["index"]
    print("[shadow_touch_test] keys: w/s offset, e/d patch, -/= drempel, a/f hoek, q=stop", flush=True)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ts += 1
            res = landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)

            out = frame.copy()
            rad = math.radians(angle)
            ux, uy = math.cos(rad), math.sin(rad)

            index_touch = False
            n_touch = 0
            index_profile = None
            if res and res.hand_landmarks:
                for hand in res.hand_landmarks:
                    for li in FINGER_TIPS.values():
                        if li >= len(hand):
                            continue
                        fx, fy = hand[li].x * w, hand[li].y * h
                        cx, cy = fx + ux * offset, fy + uy * offset
                        m = patch_mean(gray, cx, cy, half)
                        touch = m < thr
                        col = (0, 255, 0) if touch else (60, 60, 255)
                        cv2.line(out, (int(fx), int(fy)), (int(cx), int(cy)), (200, 200, 0), 1)
                        cv2.rectangle(out, (int(cx - half), int(cy - half)),
                                      (int(cx + half), int(cy + half)), col, 2)
                        cv2.circle(out, (int(fx), int(fy)), 7, col, -1)
                        if touch:
                            n_touch += 1
                        if li == idx_tip:
                            if touch:
                                index_touch = True
                            index_profile = [patch_mean(gray, fx + ux * k, fy + uy * k, 4)
                                             for k in range(0, 120, 3)]

            label = "TOUCH (wijsvinger)" if index_touch else "geen touch"
            col = (0, 255, 0) if index_touch else (60, 60, 255)
            cv2.putText(out, label, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.3, col, 3, cv2.LINE_AA)
            cv2.putText(out, f"raken: {n_touch}   offset={offset}  patch={half * 2}  "
                             f"drempel={thr}  hoek={int(angle)}",
                        (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 2, cv2.LINE_AA)
            cv2.putText(out, "w/s offset  e/d patch  -/= drempel  a/f hoek  q=stop",
                        (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)

            # Profielgrafiek: helderheid langs de straal onder de wijsvinger.
            if index_profile:
                gx, gy, gw, gh = w - 260, 40, 240, 120
                cv2.rectangle(out, (gx, gy), (gx + gw, gy + gh), (40, 40, 40), -1)
                ty = gy + gh - int(thr / 255 * gh)
                cv2.line(out, (gx, ty), (gx + gw, ty), (0, 0, 255), 1)  # drempellijn
                pts = []
                for i, b in enumerate(index_profile):
                    px = gx + int(i / max(1, len(index_profile) - 1) * gw)
                    py = gy + gh - int(b / 255 * gh)
                    pts.append((px, py))
                for i in range(1, len(pts)):
                    cv2.line(out, pts[i - 1], pts[i], (0, 255, 255), 1)
                cv2.putText(out, "helderheid onder wijsvinger", (gx, gy - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1, cv2.LINE_AA)

            cv2.imshow(win, out)
            k = cv2.waitKey(1) & 0xFF
            if k in (ord("q"), 27):
                break
            elif k == ord("w"):
                offset = max(2, offset - 2)
            elif k == ord("s"):
                offset += 2
            elif k == ord("e"):
                half = min(40, half + 1)
            elif k == ord("d"):
                half = max(2, half - 1)
            elif k == ord("-"):
                thr = max(0, thr - 5)
            elif k in (ord("="), ord("+")):
                thr = min(255, thr + 5)
            elif k == ord("a"):
                angle -= 5
            elif k == ord("f"):
                angle += 5
    finally:
        cap.release()
        landmarker.close()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
