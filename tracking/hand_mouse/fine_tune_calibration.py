#!/usr/bin/env python3
"""
fine_tune_calibration.py — 4×4 vinger-naar-stip kalibratie.

Loopt NA de gewone kalibratie. Doel: koppel de DJI-cam coördinaten direct
aan de ECHTE positie waar de gebruikers wijsvinger op het beamer-scherm
landt. Lost issues op zoals:
  - DJI ziet beamer op de kop / scheef → muis loopt verkeerde as
  - Optische 9×9 dot-detectie was iets off door perspectief
  - Vinger reach ≠ exacte projectie-mapping

Hoe:
  1. Projecteert 4×4 = 16 stippen op het beamer-scherm, één voor één
  2. Per stip: gebruiker tikt en houdt vast met wijsvinger
  3. Animatie rond stip toont 4-sec hold-progressie
  4. Tijdens hold: DJI registreert de gemiddelde fingertip cam-pixel positie
  5. iPhone bevestigt dat de vinger ook daadwerkelijk de tafel raakt
  6. Na 16 stippen: cv2.findHomography → corrigerende cam→scherm mapping
  7. Opgeslagen als `finger_homography` in calibration_dual.json

Gebruik:
  cd "/.../tracking/hand_mouse" && \
    ../dji_tracker/.venv/bin/python fine_tune_calibration.py \
      --top-idx 0 --side-idx 2 --display-idx 1 --hold-secs 4
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

import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

import hand_mouse as hm

# Hergebruik de helpers uit dual_cam_tracker
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dual_cam_tracker import is_touching_side  # type: ignore

log = logging.getLogger("fine_tune")

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = HERE / "hand_landmarker.task"
DEFAULT_CALIB = HERE / "calibration_dual.json"

LM_INDEX_TIP = 8

# Visueel
DOT_RADIUS = 36          # pulserende stip
RING_RADIUS = 70         # animatie-ring rond stip
COUNTDOWN_FRAMES = 30    # frames waarover medianen worden genomen


# ——— Camera-helpers ————————————————————————————————————————————————————
def open_cam(idx: int, label: str) -> cv2.VideoCapture | None:
    cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)
    if not cap.isOpened():
        log.error("kan %s-cam index %d niet openen", label, idx)
        cap.release()
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    for _ in range(8):
        cap.grab()
    return cap


def make_landmarker(model_path: Path, num_hands: int = 1) -> mp_vision.HandLandmarker:
    base_options = mp_tasks.BaseOptions(model_asset_path=str(model_path))
    options = mp_vision.HandLandmarkerOptions(
        base_options=base_options,
        num_hands=num_hands,
        running_mode=mp_vision.RunningMode.VIDEO,
        min_hand_detection_confidence=0.3,
        min_hand_presence_confidence=0.3,
        min_tracking_confidence=0.3,
    )
    return mp_vision.HandLandmarker.create_from_options(options)


def detect_index_tip(landmarker, frame_bgr, ts_ms: int) -> tuple[float, float] | None:
    h, w = frame_bgr.shape[:2]
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = landmarker.detect_for_video(mp_image, ts_ms)
    if not res or not res.hand_landmarks:
        return None
    lm = res.hand_landmarks[0][LM_INDEX_TIP]
    return (lm.x * w, lm.y * h)


# ——— Projectie ————————————————————————————————————————————————————————
def open_overlay(display: dict) -> str:
    win = "fine-tune"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.moveWindow(win, display["x"], display["y"])
    cv2.resizeWindow(win, display["w"], display["h"])
    try:
        cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    except Exception:
        pass
    return win


def render_dot_with_progress(display: dict, x: int, y: int,
                              progress: float, instruction: str,
                              dot_num: int, total: int,
                              phase: str = "wachten") -> np.ndarray:
    """Render volledig scherm met:
       - zwarte achtergrond
       - pulserende stip op (x,y)
       - progress-ring rondom (vult op als progress 0..1)
       - tekst onderaan
    """
    img = np.zeros((display["h"], display["w"], 3), dtype=np.uint8)

    # Pulserend formaat van de dot
    pulse = int(6 * (0.5 + 0.5 * np.sin(time.monotonic() * 6)))
    color = (0, 220, 0) if phase == "houden" else (60, 180, 255)

    # Hoofd-dot
    cv2.circle(img, (x, y), DOT_RADIUS + pulse, color, -1, cv2.LINE_AA)
    cv2.circle(img, (x, y), DOT_RADIUS + pulse + 6, (255, 255, 255), 2, cv2.LINE_AA)

    # Progress-ring (4-sec hold)
    if progress > 0:
        end_angle = int(360 * progress)
        cv2.ellipse(img, (x, y), (RING_RADIUS, RING_RADIUS),
                    -90, 0, end_angle, (50, 230, 50), 6, cv2.LINE_AA)
        # Achtergrond-ring (vol cirkel licht)
        cv2.circle(img, (x, y), RING_RADIUS, (60, 60, 60), 2, cv2.LINE_AA)

    # Tekst
    cv2.putText(img, f"{dot_num}/{total}  —  {instruction}",
                (40, display["h"] - 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(img, "ESC = annuleren",
                (40, display["h"] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (160, 160, 160), 1, cv2.LINE_AA)
    return img


def make_grid(display: dict, rows: int = 4, cols: int = 4,
               margin_frac: float = 0.12) -> list[tuple[int, int]]:
    """Genereer N×M stippen-grid in display-pixel coordinaten."""
    pts = []
    mx = int(display["w"] * margin_frac)
    my = int(display["h"] * margin_frac)
    for r in range(rows):
        for c in range(cols):
            x = mx + (display["w"] - 2 * mx) * c // max(1, cols - 1)
            y = my + (display["h"] - 2 * my) * r // max(1, rows - 1)
            pts.append((x, y))
    return pts


# ——— Per-stip wachten + capturen ——————————————————————————————————————
def capture_one_dot(
    top_cap, side_cap, top_lm, side_lm,
    display: dict, win: str,
    screen_x: int, screen_y: int,
    dot_num: int, total: int,
    hold_secs: float,
    calib_for_side_check,
) -> tuple[float, float] | None:
    """Wacht tot iPhone zegt 'touching' EN sample DJI's index-fingertip.

    Returns: (avg_cam_x, avg_cam_y) over de hold-periode, of None bij ESC.
    """
    cam_samples: list[tuple[float, float]] = []
    hold_started_at: float | None = None
    last_touching_ts = 0
    progress = 0.0
    instruction = "tik en houd vast op de stip"
    phase = "wachten"

    while True:
        # ——— Lees beide cams ———
        ok_t, frame_t = top_cap.read()
        ok_s, frame_s = side_cap.read()
        if not ok_t or not ok_s:
            time.sleep(0.01)
            continue
        ts_ms = int(time.monotonic() * 1000)

        # ——— Detect vinger in DJI ———
        tip_top = detect_index_tip(top_lm, frame_t, ts_ms)

        # ——— Detect vinger + touch in iPhone ———
        tip_side = detect_index_tip(side_lm, frame_s, ts_ms)
        is_touching = False
        if tip_side is not None and calib_for_side_check is not None:
            is_touching = is_touching_side(
                tip_side[0], tip_side[1],
                calib_for_side_check.table_y_pixel,
                calib_for_side_check.touch_threshold_px,
                side_zone_bottom=calib_for_side_check.side_zone_bottom,
                side_zone_top=calib_for_side_check.side_zone_top,
            )

        # ——— Hold-logica ———
        if is_touching and tip_top is not None:
            if hold_started_at is None:
                hold_started_at = time.monotonic()
                cam_samples = []
            cam_samples.append(tip_top)
            elapsed = time.monotonic() - hold_started_at
            progress = min(1.0, elapsed / hold_secs)
            phase = "houden"
            remaining = max(0.0, hold_secs - elapsed)
            instruction = f"HOUD VAST  ({remaining:.1f}s)"
            if progress >= 1.0 and len(cam_samples) >= 8:
                # Klaar! Neem median van de laatste samples voor stabiliteit.
                arr = np.array(cam_samples[-COUNTDOWN_FRAMES:])
                med_x = float(np.median(arr[:, 0]))
                med_y = float(np.median(arr[:, 1]))
                return (med_x, med_y)
        else:
            hold_started_at = None
            cam_samples = []
            progress = 0.0
            phase = "wachten"
            if tip_top is None:
                instruction = "DJI ziet je vinger niet — beweeg in beeld"
            elif tip_side is None:
                instruction = "iPhone ziet je vinger niet — tik op de stip"
            elif not is_touching:
                instruction = "tik en houd vast op de stip"

        # ——— Render ———
        img = render_dot_with_progress(display, screen_x, screen_y,
                                        progress, instruction,
                                        dot_num, total, phase)
        cv2.imshow(win, img)
        key = cv2.waitKey(20) & 0xFF
        if key == 27:  # ESC
            return None


# ——— Main ——————————————————————————————————————————————————————————————
def main() -> int:
    parser = argparse.ArgumentParser(
        description="4×4 vinger-naar-stip kalibratie — corrigeert mapping.",
    )
    parser.add_argument("--top-idx", type=int, default=0)
    parser.add_argument("--side-idx", type=int, default=2)
    parser.add_argument("--display-idx", type=int, default=None,
                        help="Scherm voor projectie. Default: auto-pick beamer.")
    parser.add_argument("--rows", type=int, default=4)
    parser.add_argument("--cols", type=int, default=4)
    parser.add_argument("--hold-secs", type=float, default=4.0)
    parser.add_argument("--calib", type=Path, default=DEFAULT_CALIB)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.calib.exists():
        log.error("Geen calibration_dual.json gevonden op %s — eerst de gewone "
                  "kalibratie draaien.", args.calib)
        return 1
    if not args.model.exists():
        log.error("MediaPipe model niet gevonden: %s", args.model)
        return 1

    # Display kiezen
    displays = hm.list_displays()
    display_idx = args.display_idx
    if display_idx is None:
        for i, d in enumerate(displays):
            if not d.get("main"):
                display_idx = i
                break
    display = hm.pick_display(displays, display_idx)
    log.info("Projectie op scherm #%s: %dx%d @ (%d,%d) main=%s",
             display_idx, display["w"], display["h"],
             display["x"], display["y"], display.get("main"))

    # Open cams
    top_cap = open_cam(args.top_idx, "top-DJI")
    side_cap = open_cam(args.side_idx, "side-iPhone")
    if top_cap is None or side_cap is None:
        return 1

    # MediaPipe per cam
    top_lm = make_landmarker(args.model)
    side_lm = make_landmarker(args.model)

    # Laad bestaande kalibratie zodat we de side-zone kennen voor touch-detectie
    from dual_cam_tracker import Calibration  # late import
    calib = Calibration.load(args.calib)

    # Open beamer fullscreen
    win = open_overlay(display)

    # Stippen-grid
    dots = make_grid(display, args.rows, args.cols)
    total = len(dots)

    # Countdown vóór start
    for sec in range(3, 0, -1):
        img = np.zeros((display["h"], display["w"], 3), dtype=np.uint8)
        cv2.putText(img, f"start over {sec}…",
                    (display["w"] // 2 - 200, display["h"] // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.5, (255, 255, 255), 4, cv2.LINE_AA)
        cv2.putText(img, "Stip pulserend = wachten op tik. Pak je vinger klaar.",
                    (display["w"] // 2 - 480, display["h"] // 2 + 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (180, 180, 180), 2, cv2.LINE_AA)
        cv2.imshow(win, img)
        cv2.waitKey(1000)

    # Loop over stippen
    pairs: list[tuple[tuple[float, float], tuple[int, int]]] = []
    try:
        for i, (sx, sy) in enumerate(dots, start=1):
            res = capture_one_dot(
                top_cap, side_cap, top_lm, side_lm,
                display, win, sx, sy, i, total,
                args.hold_secs, calib,
            )
            if res is None:
                log.warning("Geannuleerd op stip %d/%d", i, total)
                return 1
            cam_x, cam_y = res
            pairs.append(((cam_x, cam_y), (sx, sy)))
            log.info("[%d/%d] dot screen=(%d,%d)  cam=(%.1f,%.1f)",
                     i, total, sx, sy, cam_x, cam_y)

            # Korte "✓"-flits
            img = np.zeros((display["h"], display["w"], 3), dtype=np.uint8)
            cv2.circle(img, (sx, sy), DOT_RADIUS + 20, (50, 230, 50), -1, cv2.LINE_AA)
            cv2.putText(img, "✓",
                        (sx - 18, sy + 14), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                        (255, 255, 255), 3, cv2.LINE_AA)
            cv2.imshow(win, img)
            cv2.waitKey(400)

    finally:
        top_cap.release()
        side_cap.release()
        top_lm.close()
        side_lm.close()
        cv2.destroyAllWindows()

    if len(pairs) < 4:
        log.error("Te weinig metingen voor homografie (%d < 4)", len(pairs))
        return 1

    # Bereken homografie: cam-pixel → scherm-pixel
    cam_pts = np.array([p[0] for p in pairs], dtype=np.float32)
    scr_pts = np.array([p[1] for p in pairs], dtype=np.float32)
    H, mask = cv2.findHomography(cam_pts, scr_pts, method=cv2.RANSAC,
                                  ransacReprojThreshold=20.0)
    if H is None:
        log.error("Homografie-berekening faalde")
        return 1

    inliers = int(mask.sum()) if mask is not None else len(pairs)
    log.info("Homografie OK met %d/%d inliers", inliers, len(pairs))

    # Sla op in calibration_dual.json
    data = json.loads(args.calib.read_text())
    data["finger_homography"] = H.tolist()
    data["finger_calib_pairs"] = [
        {"cam": list(p[0]), "screen": list(p[1])} for p in pairs
    ]
    data["finger_calib_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    args.calib.write_text(json.dumps(data, indent=2))
    log.info("✓ finger_homography opgeslagen in %s", args.calib)
    log.info("De tracker gebruikt deze nu automatisch i.p.v. de optische 9×9.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
