#!/usr/bin/env python3
"""
calibrate_all_fingers.py — per-vinger OFFSET-verfijning (10 vingers × 5 posities).

Bouwt GEEN aparte homografieën meer (die verdraaiden de hele positie en stuurden
"de verkeerde kant op"). In plaats daarvan meet dit script per vinger één kleine,
constante OFFSET (dx, dy) t.o.v. de 9×9-basis uit calibrate_dual.py:

    offset[vinger] = mediaan over de 5 stippen van ( stip_doel − 9×9_basis(DJI_pixel) )

De tracker doet runtime:  scherm = 9×9_basis(vinger) + offset[vinger].
Een offset is puur een verschuiving en kan dus nooit "de verkeerde kant op" sturen.

Volgorde (zoals afgesproken):
   1=L-pink, 2=L-ring, 3=L-middle, 4=L-index, 5=L-thumb,
   6=R-thumb, 7=R-index, 8=R-middle, 9=R-ring, 10=R-pinky

Per vinger 5 schermposities: linksboven, rechtsboven, midden, linksonder,
rechtsonder. De iPhone (side) bepaalt alleen of de vinger de tafel raakt
(touch-gate); de offset komt volledig uit de DJI (top) t.o.v. de 9×9-basis.

Bediening per stip:
  - r        = huidige stip resetten (vinger los, opnieuw)
  - ESC      = afbreken
  - hold     = automatisch opslaan en door naar volgende

Output: 'finger_offsets' dict in calibration_dual.json, bv. {"R-index": [dx, dy]}.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dual_cam_tracker import is_touching_side, Calibration, map_screen  # type: ignore

log = logging.getLogger("calibrate_all_fingers")

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = HERE / "hand_landmarker.task"
DEFAULT_CALIB = HERE / "calibration_dual.json"

# ——— Configuratie ————————————————————————————————————————————————————————
# Vingervolgorde + MediaPipe landmark indices voor de fingertip.
# Handedness uit MediaPipe: "Left" of "Right" — wij gebruiken kort "L"/"R".
FINGER_SEQUENCE = [
    ("L", "pinky",  20, "Linker pink"),
    ("L", "ring",   16, "Linker ringvinger"),
    ("L", "middle", 12, "Linker middelvinger"),
    ("L", "index",   8, "Linker wijsvinger"),
    ("L", "thumb",   4, "Linker duim"),
    ("R", "thumb",   4, "Rechter duim"),
    ("R", "index",   8, "Rechter wijsvinger"),
    ("R", "middle", 12, "Rechter middelvinger"),
    ("R", "ring",   16, "Rechter ringvinger"),
    ("R", "pinky",  20, "Rechter pink"),
]

# Vijf posities per vinger (in genormaliseerde scherm-coords, met marge).
POSITION_FRACS = [
    (0.15, 0.18, "linksboven"),
    (0.85, 0.18, "rechtsboven"),
    (0.50, 0.50, "midden"),
    (0.15, 0.82, "linksonder"),
    (0.85, 0.82, "rechtsonder"),
]

DOT_RADIUS = 36
RING_RADIUS = 72
MEDIAN_FRAMES = 30   # laatste N frames waarover we de mediaan nemen
COUNTDOWN_BEFORE_START_S = 5


# ——— Cam-helpers ————————————————————————————————————————————————————————
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


def make_landmarker(model_path: Path, num_hands: int = 2) -> mp_vision.HandLandmarker:
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


# MediaPipe VIDEO-modus eist per landmarker STRIKT stijgende timestamps. Twee
# calls in dezelfde milliseconde (of een herhaalde call op hetzelfde frame)
# crashen met "Input timestamp must be monotonically increasing". We houden
# daarom per landmarker een eigen teller bij die altijd minstens +1 gaat.
_last_ts: dict[int, int] = {}


def _next_ts(landmarker) -> int:
    key = id(landmarker)
    now = int(time.monotonic() * 1000)
    nxt = max(now, _last_ts.get(key, 0) + 1)
    _last_ts[key] = nxt
    return nxt


def detect_fingertip(landmarker, frame_bgr, lm_idx: int,
                     hand_label: str | None = None
                     ) -> tuple[float, float] | None:
    """Eén detect-call per frame. Zoekt de fingertip `lm_idx`.

    Als `hand_label` ("Left"/"Right") gegeven is, voorkeur voor die hand; valt
    terug op de eerst-gevonden hand als de handedness niet matcht (kalibratie
    verwacht toch maar één hand tegelijk in beeld).
    """
    h, w = frame_bgr.shape[:2]
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = landmarker.detect_for_video(mp_image, _next_ts(landmarker))
    if not res or not res.hand_landmarks:
        return None
    target_idx = 0
    if hand_label is not None and res.handedness:
        for i, hd in enumerate(res.handedness):
            if hd[0].category_name.lower().startswith(hand_label.lower()):
                target_idx = i
                break
    if target_idx >= len(res.hand_landmarks):
        target_idx = 0
    lm = res.hand_landmarks[target_idx][lm_idx]
    return (lm.x * w, lm.y * h)


# ——— Display + render ——————————————————————————————————————————————————
def open_overlay(display: dict) -> str:
    win = "calibrate-all-fingers"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.moveWindow(win, display["x"], display["y"])
    cv2.resizeWindow(win, display["w"], display["h"])
    try:
        cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    except Exception:
        pass
    return win


def render_dot_with_progress(display: dict, x: int, y: int,
                              progress: float, phase: str,
                              finger_name_nl: str,
                              finger_num: int, finger_total: int,
                              dot_num: int, dot_total: int,
                              position_label: str,
                              status_msg: str) -> np.ndarray:
    img = np.zeros((display["h"], display["w"], 3), dtype=np.uint8)

    # Pulserende dot
    pulse = int(6 * (0.5 + 0.5 * np.sin(time.monotonic() * 6)))
    if phase == "houden":
        color = (0, 220, 0)
    elif phase == "klaar":
        color = (50, 230, 50)
    else:
        color = (60, 180, 255)
    cv2.circle(img, (x, y), DOT_RADIUS + pulse, color, -1, cv2.LINE_AA)
    cv2.circle(img, (x, y), DOT_RADIUS + pulse + 6, (255, 255, 255), 2, cv2.LINE_AA)

    # Progress-ring
    if progress > 0:
        end_angle = int(360 * progress)
        cv2.ellipse(img, (x, y), (RING_RADIUS, RING_RADIUS),
                    -90, 0, end_angle, (50, 230, 50), 6, cv2.LINE_AA)
        cv2.circle(img, (x, y), RING_RADIUS, (60, 60, 60), 2, cv2.LINE_AA)

    # Header — vinger info
    cv2.putText(img,
                f"Vinger {finger_num}/{finger_total}: {finger_name_nl}",
                (40, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(img,
                f"Stip {dot_num}/{dot_total}: {position_label}",
                (40, 130),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2, cv2.LINE_AA)

    # Footer — status / instructies
    cv2.putText(img, status_msg,
                (40, display["h"] - 80),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(img, "r = opnieuw beginnen   |   ESC = annuleren",
                (40, display["h"] - 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (160, 160, 160), 1, cv2.LINE_AA)
    return img


def render_countdown(display: dict, sec: int, total: int) -> np.ndarray:
    img = np.zeros((display["h"], display["w"], 3), dtype=np.uint8)
    cv2.putText(img, f"Start over {sec}…",
                (display["w"] // 2 - 280, display["h"] // 2 - 30),
                cv2.FONT_HERSHEY_SIMPLEX, 3.0, (255, 255, 255), 5, cv2.LINE_AA)
    cv2.putText(img, f"{total} stippen × ~3 sec = ~{(total * 3) // 60}:{(total * 3) % 60:02d} min",
                (display["w"] // 2 - 320, display["h"] // 2 + 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (180, 180, 180), 2, cv2.LINE_AA)
    cv2.putText(img, "Pak je linker pink klaar.",
                (display["w"] // 2 - 280, display["h"] // 2 + 90),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2, cv2.LINE_AA)
    return img


def render_done(display: dict, n_fingers: int, n_dots: int) -> np.ndarray:
    img = np.zeros((display["h"], display["w"], 3), dtype=np.uint8)
    cv2.putText(img, "✓ Offset-kalibratie voltooid",
                (display["w"] // 2 - 420, display["h"] // 2 - 40),
                cv2.FONT_HERSHEY_SIMPLEX, 2.0, (50, 230, 50), 4, cv2.LINE_AA)
    cv2.putText(img, f"{n_fingers} vingers gekalibreerd ({n_dots} metingen)",
                (display["w"] // 2 - 350, display["h"] // 2 + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, (200, 200, 200), 2, cv2.LINE_AA)
    cv2.putText(img, "Sluit dit venster — opslag is voltooid.",
                (display["w"] // 2 - 320, display["h"] // 2 + 70),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (160, 160, 160), 1, cv2.LINE_AA)
    return img


# ——— Per-stip capture-logica ——————————————————————————————————————————
def capture_one_dot(
    top_cap, side_cap, top_lm, side_lm,
    display: dict, win: str,
    screen_x: int, screen_y: int,
    hand_label: str, lm_idx: int,
    finger_name_nl: str,
    finger_num: int, finger_total: int,
    dot_num: int, dot_total: int,
    position_label: str,
    hold_secs: float,
    side_calib_for_touch,
):  # -> ((top_x,top_y),(side_x,side_y)) | None | "RESTART"
    """Wacht tot iPhone 'touching' + DJI ziet de juiste vinger. Hold X sec.

    Slaat per frame ZOWEL de DJI- als de iPhone-positie van DEZELFDE vinger op.
    De iPhone bepaalt ook of de vinger de tafel raakt — met dezelfde vinger
    (niet altijd de wijsvinger), zodat o.a. de duim correct werkt.

    Returns:
      ((top_x, top_y), (side_x, side_y)) bij voltooien,
      None bij ESC, "RESTART" bij 'r'.
    """
    top_samples: list[tuple[float, float]] = []
    side_samples: list[tuple[float, float]] = []
    hold_started_at: float | None = None
    progress = 0.0
    phase = "wachten"
    status_msg = "Tik en houd vast met je " + finger_name_nl.lower()

    while True:
        ok_t, frame_t = top_cap.read()
        ok_s, frame_s = side_cap.read()
        if not ok_t or not ok_s:
            time.sleep(0.01)
            continue
        # Detect DEZELFDE vinger in beide camera's.
        tip_top = detect_fingertip(top_lm, frame_t, lm_idx, hand_label)
        tip_side = detect_fingertip(side_lm, frame_s, lm_idx, hand_label)

        # iPhone bepaalt touching — met DEZELFDE vinger (fixt o.a. de duim).
        is_touching = False
        if side_calib_for_touch is not None and tip_side is not None:
            is_touching = is_touching_side(
                tip_side[0], tip_side[1],
                side_calib_for_touch.table_y_pixel,
                side_calib_for_touch.touch_threshold_px,
                side_zone_bottom=side_calib_for_touch.side_zone_bottom,
                side_zone_top=side_calib_for_touch.side_zone_top,
            )

        # Hold start als DJI én iPhone de vinger zien ÉN iPhone zegt touching.
        if is_touching and tip_top is not None and tip_side is not None:
            if hold_started_at is None:
                hold_started_at = time.monotonic()
                top_samples = []
                side_samples = []
            top_samples.append(tip_top)
            side_samples.append(tip_side)
            elapsed = time.monotonic() - hold_started_at
            progress = min(1.0, elapsed / hold_secs)
            phase = "houden"
            remaining = max(0.0, hold_secs - elapsed)
            status_msg = f"HOUD VAST … {remaining:.1f}s"
            if progress >= 1.0 and len(top_samples) >= 6:
                t_arr = np.array(top_samples[-MEDIAN_FRAMES:])
                s_arr = np.array(side_samples[-MEDIAN_FRAMES:])
                top_med = (float(np.median(t_arr[:, 0])), float(np.median(t_arr[:, 1])))
                side_med = (float(np.median(s_arr[:, 0])), float(np.median(s_arr[:, 1])))
                return (top_med, side_med)
        else:
            hold_started_at = None
            top_samples = []
            side_samples = []
            progress = 0.0
            phase = "wachten"
            if tip_top is None:
                status_msg = f"DJI ziet de {finger_name_nl.lower()} niet — kom in beeld"
            elif tip_side is None:
                status_msg = f"iPhone ziet de {finger_name_nl.lower()} niet"
            elif not is_touching:
                status_msg = f"Tik met je {finger_name_nl.lower()} op de stip"

        img = render_dot_with_progress(
            display, screen_x, screen_y, progress, phase,
            finger_name_nl, finger_num, finger_total,
            dot_num, dot_total, position_label, status_msg)
        cv2.imshow(win, img)
        key = cv2.waitKey(20) & 0xFF
        if key == 27:
            return None
        if key == ord("r"):
            return "RESTART"  # type: ignore[return-value]


# ——— Main ——————————————————————————————————————————————————————————————
def main() -> int:
    parser = argparse.ArgumentParser(
        description="50-punts per-vinger kalibratie (10 vingers x 5 posities).",
    )
    parser.add_argument("--top-idx", type=int, default=0)
    parser.add_argument("--side-idx", type=int, default=2)
    parser.add_argument("--display-idx", type=int, default=None,
                        help="Scherm voor projectie. Default: auto-pick beamer.")
    parser.add_argument("--hold-secs", type=float, default=4.0,
                        help="Hold-tijd per stip in seconden (default 4).")
    parser.add_argument("--calib", type=Path, default=DEFAULT_CALIB)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.calib.exists():
        log.error("Geen calibration_dual.json — eerst calibrate_dual.py draaien.")
        return 1
    if not args.model.exists():
        log.error("MediaPipe model niet gevonden: %s", args.model)
        return 1

    # De offset wordt berekend t.o.v. de 9×9-basis — die MOET er dus zijn.
    side_calib = Calibration.load(args.calib)
    if not side_calib.has_grid:
        log.error("calibration_dual.json heeft geen 9×9 grid (samples/cols/rows). "
                  "Draai eerst calibrate_dual.py — de offset wordt t.o.v. die "
                  "9×9-basis berekend.")
        return 1

    # Display
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

    # Cams
    top_cap = open_cam(args.top_idx, "top-DJI")
    side_cap = open_cam(args.side_idx, "side-iPhone")
    if top_cap is None or side_cap is None:
        return 1

    # DJI-frameafmetingen — nodig om de DJI-pixel correct te normaliseren in de
    # 9×9-basis (map_screen deelt door cam_w/cam_h). Moet de resolutie zijn die
    # detect_fingertip óók ziet, dus lezen we een echt frame.
    ok_probe, probe = top_cap.read()
    if not ok_probe or probe is None:
        log.error("Kan geen DJI-frame lezen voor cam-afmetingen.")
        top_cap.release()
        side_cap.release()
        return 1
    top_cam_h, top_cam_w = probe.shape[:2]
    log.info("DJI-frame: %dx%d", top_cam_w, top_cam_h)

    top_lm = make_landmarker(args.model, num_hands=2)
    side_lm = make_landmarker(args.model, num_hands=1)

    win = open_overlay(display)

    # Countdown
    total_dots = len(FINGER_SEQUENCE) * len(POSITION_FRACS)
    for sec in range(COUNTDOWN_BEFORE_START_S, 0, -1):
        cv2.imshow(win, render_countdown(display, sec, total_dots))
        cv2.waitKey(1000)

    # Loop over alle 50 metingen. Per vinger bewaren we de DJI-meting gekoppeld
    # aan de schermpositie van de stip. De iPhone-meting gebruiken we alleen voor
    # de touch-gate (en in de log), niet voor de offset zelf.
    top_pairs: dict[str, list[tuple[tuple[float, float], tuple[int, int]]]] = {}
    try:
        finger_total = len(FINGER_SEQUENCE)
        for finger_idx, (hand_label, finger_name, lm_idx, name_nl) in enumerate(FINGER_SEQUENCE, start=1):
            key = f"{hand_label}-{finger_name}"
            top_pairs[key] = []

            for dot_idx, (xf, yf, pos_label) in enumerate(POSITION_FRACS, start=1):
                sx = int(xf * display["w"])
                sy = int(yf * display["h"])
                while True:  # restart-loop
                    res = capture_one_dot(
                        top_cap, side_cap, top_lm, side_lm,
                        display, win, sx, sy,
                        hand_label, lm_idx, name_nl,
                        finger_idx, finger_total,
                        dot_idx, len(POSITION_FRACS),
                        pos_label, args.hold_secs, side_calib,
                    )
                    if res is None:
                        log.warning("Geannuleerd")
                        return 1
                    if res == "RESTART":
                        log.info("[%s stip %d] reset op verzoek", key, dot_idx)
                        continue
                    break

                top_med, side_med = res  # type: ignore[misc]
                top_pairs[key].append((top_med, (sx, sy)))
                log.info("[%2d/%2d %s] dot %d/5 (%s) — screen=(%d,%d) "
                         "DJI=(%.1f,%.1f) iPhone=(%.1f,%.1f)",
                         finger_idx, finger_total, name_nl,
                         dot_idx, pos_label, sx, sy,
                         top_med[0], top_med[1], side_med[0], side_med[1])

                # Korte ✓-flits
                img = np.zeros((display["h"], display["w"], 3), dtype=np.uint8)
                cv2.circle(img, (sx, sy), DOT_RADIUS + 20, (50, 230, 50), -1, cv2.LINE_AA)
                cv2.putText(img, "✓",
                            (sx - 18, sy + 14), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                            (255, 255, 255), 3, cv2.LINE_AA)
                cv2.imshow(win, img)
                cv2.waitKey(300)

    finally:
        top_cap.release()
        side_cap.release()
        top_lm.close()
        side_lm.close()

    # Bereken per vinger één OFFSET (dx, dy) t.o.v. de 9×9-basis. Per stip:
    #   basis = map_screen(DJI_pixel)  (exact dezelfde 9×9-mapping als de tracker)
    #   doel  = stip-positie, omgerekend naar de scherm-ruimte van de kalibratie
    #   delta = doel − basis
    # De offset = de MEDIAAN van de delta's over de 5 stippen (robuust tegen één
    # misgrepen stip). De tracker telt deze runtime additief bij map_screen() op.
    def compute_offsets(pairs_dict):
        out: dict[str, list[float]] = {}
        n_dots = 0
        for key, pairs in pairs_dict.items():
            if not pairs:
                log.warning("[%s] geen metingen — overslaan", key)
                continue
            deltas = []
            for cam_pt, (sx, sy) in pairs:
                base_x, base_y = map_screen(cam_pt, side_calib,
                                            top_cam_w, top_cam_h,
                                            use_offsets=False)
                # Stip-doel → scherm-ruimte van de kalibratie (meestal 1:1).
                tx = sx / display["w"] * side_calib.screen_w
                ty = sy / display["h"] * side_calib.screen_h
                deltas.append((tx - base_x, ty - base_y))
            arr = np.array(deltas, dtype=np.float64)
            dx = float(np.median(arr[:, 0]))
            dy = float(np.median(arr[:, 1]))
            out[key] = [dx, dy]
            n_dots += len(deltas)
            # Spreiding = max−min per as. Groot bereik ⇒ de fout is plaats-
            # afhankelijk (gradiënt), wat eigenlijk het 9×9-grid hoort op te
            # vangen, niet een constante offset. Handig diagnostisch signaal.
            rng_x = float(arr[:, 0].max() - arr[:, 0].min())
            rng_y = float(arr[:, 1].max() - arr[:, 1].min())
            log.info("[%-8s] offset = (%+6.1f, %+6.1f) px  | %d stippen, "
                     "spreiding dx=%.0f dy=%.0f",
                     key, dx, dy, len(deltas), rng_x, rng_y)
        return out, n_dots

    offsets, n_dots = compute_offsets(top_pairs)

    # Opslaan in calibration_dual.json. De oude per-vinger homografie-aanpak is
    # vervangen door offsets; verouderde keys ruimen we op zodat het bestand niet
    # misleidt (de tracker negeerde ze al).
    data = json.loads(args.calib.read_text())
    data["finger_offsets"] = offsets
    data["finger_offsets_calibrated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    for stale in ("finger_homographies", "finger_homographies_top",
                  "finger_homographies_side", "finger_calibrated_at"):
        data.pop(stale, None)
    args.calib.write_text(json.dumps(data, indent=2))
    log.info("✓ %d vinger-offsets opgeslagen in %s (%d metingen totaal)",
             len(offsets), args.calib, n_dots)

    # Eindscherm
    cv2.imshow(win, render_done(display, len(offsets), n_dots))
    cv2.waitKey(2500)
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
