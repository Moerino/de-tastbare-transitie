#!/usr/bin/env python3
"""
calibrate_dual.py — 9×9 grid-kalibratie voor de dual-cam tracker.

Hergebruikt de werkende `auto_calibrate` uit `hand_mouse.py`:

Fase A — Top-camera grid kalibratie:
  Projecteert oplopend witte dots op het beamer-scherm (full-screen) en
  detecteert per dot waar hij in het top-cam-beeld verschijnt via
  background-subtraction. Resultaat: cols×rows sample-punten in
  genormaliseerde cam-coords + per-cel homography voor lokale
  distortie-correctie.

Fase B — Side-camera tafel-vlak meting:
  Gebruiker legt wijsvinger plat op tafel → meet pixel-Y over 30 frames.
  Daarna 1 cm omhoog → meet lift-Y. touch_threshold_px = halverwege.

Output: calibration_dual.json met:
  - samples, cols, rows, mirror_x       (Fase A)
  - table_y_pixel, touch_threshold_px   (Fase B)
  - screen_w, screen_h, indices, timestamp

Voorbeeld:
  cd "/.../tracking/hand_mouse" && ../dji_tracker/.venv/bin/python \
     calibrate_dual.py --top-idx 3 --side-idx 0 --cols 9 --rows 9
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

# Hergebruik bewezen helpers uit de bestaande single-cam tracker.
# hand_mouse.py heeft `if __name__ == "__main__": main()` dus importeren
# voert niets uit behalve de top-level constanten + functies.
import hand_mouse as hm

log = logging.getLogger("calibrate_dual")

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = HERE / "hand_landmarker.task"
DEFAULT_OUT = HERE / "calibration_dual.json"

LM_INDEX_TIP = 8


# ——— Side-cam helpers (Fase B) —————————————————————————————————————————
def make_side_landmarker(model_path: Path) -> mp_vision.HandLandmarker:
    base_options = mp_tasks.BaseOptions(model_asset_path=str(model_path))
    options = mp_vision.HandLandmarkerOptions(
        base_options=base_options,
        num_hands=1,
        running_mode=mp_vision.RunningMode.VIDEO,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return mp_vision.HandLandmarker.create_from_options(options)


def detect_index_tip(landmarker, frame_bgr, ts_ms: int):
    h, w = frame_bgr.shape[:2]
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = landmarker.detect_for_video(mp_image, ts_ms)
    if not res or not res.hand_landmarks:
        return None
    lm = res.hand_landmarks[0][LM_INDEX_TIP]
    return (lm.x * w, lm.y * h)


def draw_status(frame, text, sub=None, color=(255, 255, 255)):
    out = frame.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 70), (0, 0, 0), -1)
    cv2.putText(out, text, (16, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA)
    if sub:
        cv2.putText(out, sub, (16, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)
    return out


def capture_hold(cap, landmarker, hold_secs: float, prompt: str, win_title: str):
    samples: list[tuple[float, float]] = []
    start = None
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        # MediaPipe VIDEO mode eist strikt monotoon stijgende ms-timestamps.
        # Een lokale counter (ts += 1) resette tussen twee capture_hold calls
        # met dezelfde landmarker → "Input timestamp must be monotonically
        # increasing". Monotonic clock fixt dit globaal.
        ts = int(time.monotonic() * 1000)
        tip = detect_index_tip(landmarker, frame, ts)
        if tip is not None:
            cv2.circle(frame, (int(tip[0]), int(tip[1])), 14, (0, 255, 0), 3)
            if start is None:
                start = time.monotonic()
            samples.append(tip)
            elapsed = time.monotonic() - start
            remaining = max(0.0, hold_secs - elapsed)
            sub = f"Houd vast... {remaining:.1f}s"
            color = (0, 255, 0)
            if elapsed >= hold_secs and len(samples) >= 10:
                avg_x = sum(p[0] for p in samples[-20:]) / min(20, len(samples))
                avg_y = sum(p[1] for p in samples[-20:]) / min(20, len(samples))
                return (avg_x, avg_y)
        else:
            start = None
            samples.clear()
            sub = "Geen vinger gedetecteerd"
            color = (0, 100, 255)
        out = draw_status(frame, prompt, sub, color)
        cv2.imshow(win_title, out)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            return None


def _default_side_zone(frame_w: int, frame_h: int, table_y: int | None) -> list[list[int]]:
    """Schat een redelijke beamer-zone polygon zonder verdere kennis.

    De side-cam ziet het beamer-scherm typisch als een dunne strip rond de
    tafel-lijn. We maken een rechthoek van ~25% beeldhoogte rond `table_y`,
    spanning over de volledige frame-breedte. Gebruiker fine-tuned in Fase C.
    """
    if table_y is None:
        table_y = frame_h // 2
    band = max(80, frame_h // 5)
    top = max(0, table_y - band)
    bot = min(frame_h - 1, table_y + band // 3)
    return [[10, top], [frame_w - 10, top], [frame_w - 10, bot], [10, bot]]


# ——— Multi-kleur dot detectie (Fase A, optioneel via --multicolor) ————————
# Voor camera's die wit moeilijk pakken (auto-exposure, HDR, etc.) cyclen we
# door meerdere kleuren per dot en pakken het sterkste signaal. Werkt ook
# voor de iPhone parallel zodat side-cam meeleert waar de beamer staat.

DETECTION_COLORS = [
    # (label, BGR)
    ("wit",     (255, 255, 255)),
    ("geel",    (  0, 255, 255)),
    ("magenta", (255,   0, 255)),
    ("cyaan",   (255, 255,   0)),
    ("rood",    (  0,   0, 255)),
    ("groen",   (  0, 255,   0)),
]


def _render_dot_in_color(display, screen_xy_norm, color_bgr, radius: int):
    """Render een dot op `screen_xy_norm` (0..1) in de gegeven BGR-kleur."""
    img = np.zeros((display["h"], display["w"], 3), dtype=np.uint8)
    cx = int(screen_xy_norm[0] * display["w"])
    cy = int(screen_xy_norm[1] * display["h"])
    cv2.circle(img, (cx, cy), radius, color_bgr, -1, cv2.LINE_AA)
    return img


def _find_blob_in_diff(frame_on, baseline, expected_px, search_radius,
                       diff_threshold: int, min_blob: int):
    """Vergelijk twee frames, vind grootste blob binnen verwachte radius.

    Returns (cx, cy, score) of None. Score = max_diff * area; hoger = beter.
    """
    if frame_on is None or baseline is None:
        return None
    diff = cv2.absdiff(frame_on, baseline)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (9, 9), 0)
    max_diff = int(gray.max())
    _, mask = cv2.threshold(gray, diff_threshold, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = 0.0
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < min_blob:
            continue
        M = cv2.moments(cnt)
        if M["m00"] == 0:
            continue
        cx = M["m10"] / M["m00"]
        cy = M["m01"] / M["m00"]
        if expected_px is not None and search_radius is not None:
            ex, ey = expected_px
            d = ((cx - ex) ** 2 + (cy - ey) ** 2) ** 0.5
            if d > search_radius:
                continue
        score = max_diff * area
        if score > best_score:
            best_score = score
            best = (cx, cy, score)
    return best


def phase_a_multicolor(top_cap, side_cap, display, cols: int, rows: int,
                      dot_radius: int, diff_threshold: int, min_blob: int,
                      color_dwell_s: float = 0.30,
                      ) -> tuple[list[tuple[float, float]], list[tuple[float, float] | None]] | None:
    """Multi-kleur dot-projectie + detectie op top-cam (+ side-cam best-effort).

    Per grid-positie: cycle door 6 kleuren (~250ms elk), capture frame na elke
    kleur, kies het sterkste blob-signaal. Werkt ook als top-cam witte dots
    afvlakt (HDR / auto-exposure).

    Side-cam meekijkt: voor elke dot wordt óók een iPhone-frame geanalyseerd.
    Krijgt geen geforceerd raster maar slaat op wat detecteerbaar was — geeft
    iPhone een eigen mapping naar het beamer-vlak voor multitouch-fusie.

    Returns: (top_samples_normalized, side_samples_pixel)
      - top_samples: 81 (x,y) in [0..1] cam-coords (genormaliseerd op frame).
      - side_samples: 81 (x,y) in pixel-coords van side-frame; None waar niet
        gedetecteerd.
    """
    # —— Phase 1: 4 hoeken globaal detecteren voor rough homography
    hm.open_calib_overlay(display)
    countdown = 8
    for sec in range(countdown, 0, -1):
        cv2.imshow(hm.CALIB_WIN, hm._render_message(
            display, ["MULTI-KLEUR KALIBRATIE", f"Stap uit het beeld... {sec}"],
            sub="Druk ESC om af te breken."))
        t_end = time.time() + 1.0
        while time.time() < t_end:
            if (cv2.waitKey(20) & 0xFF) == 27:
                hm.close_calib_overlay()
                return None

    # Baseline (zwarte projectie) voor beide cams
    cv2.imshow(hm.CALIB_WIN, hm._render_message(display, ["Baseline meten..."]))
    cv2.waitKey(120)
    cv2.imshow(hm.CALIB_WIN, hm._render_black(display))
    cv2.waitKey(800)
    for _ in range(20):
        top_cap.grab()
        if side_cap:
            side_cap.grab()
    ok, baseline_top = top_cap.read()
    if not ok:
        hm.close_calib_overlay()
        log.error("Kan geen baseline-frame van top-cam grabben")
        return None
    baseline_side = None
    if side_cap:
        ok_s, baseline_side = side_cap.read()
        if not ok_s:
            baseline_side = None
            log.warning("Kan geen baseline-frame van side-cam grabben — "
                        "iPhone-grid wordt overgeslagen")

    h_top, w_top = baseline_top.shape[:2]
    h_side, w_side = (baseline_side.shape[:2] if baseline_side is not None else (0, 0))

    # —— Detect 4 corners globaal (geen verwachte positie)
    corners_screen = [(0.02, 0.02), (0.98, 0.02), (0.98, 0.98), (0.02, 0.98)]
    corner_cam_top: list[tuple[float, float]] = []
    print(f"\n[multicolor] phase 1: 4 hoeken (dot_radius={dot_radius})")
    for i, sxy in enumerate(corners_screen):
        best = None
        best_score = 0
        for color_name, color_bgr in DETECTION_COLORS:
            cv2.imshow(hm.CALIB_WIN,
                       _render_dot_in_color(display, sxy, color_bgr, dot_radius))
            cv2.waitKey(int(color_dwell_s * 1000))
            for _ in range(8):
                top_cap.grab()
            ok, frame_on = top_cap.read()
            if not ok:
                continue
            res = _find_blob_in_diff(frame_on, baseline_top, None, None,
                                     diff_threshold, min_blob)
            if res is not None and res[2] > best_score:
                best_score = res[2]
                best = (res[0], res[1], color_name)
        if best is None:
            print(f"[multicolor] hoek {i+1}/4 NIET gedetecteerd — afbreken")
            hm.close_calib_overlay()
            return None
        corner_cam_top.append((best[0], best[1]))
        print(f"[multicolor] hoek {i+1}/4 → cam ({best[0]/w_top:.3f}, {best[1]/h_top:.3f}) "
              f"via {best[2]}")

    # Rough homography screen → cam (genormaliseerd op 0..1)
    src_screen = corners_screen
    dst_cam_norm = [(p[0]/w_top, p[1]/h_top) for p in corner_cam_top]
    H_screen_to_cam = hm.compute_homography_4pt(src_screen, dst_cam_norm)

    # Search radius schaling: ~70% van cel-diagonal
    proj_diag = ((corner_cam_top[2][0] - corner_cam_top[0][0]) ** 2 +
                 (corner_cam_top[2][1] - corner_cam_top[0][1]) ** 2) ** 0.5
    cell_cap = 0.7 * proj_diag / max(cols, rows)
    search_radius = max(50, min(0.25 * proj_diag, cell_cap * 1.4))

    # —— Phase 2: 9×9 grid met multi-kleur
    targets = hm._expected_dot_positions(cols, rows)
    print(f"\n[multicolor] phase 2: {len(targets)} dots (search radius "
          f"{int(search_radius)}px, kleuren per dot: {len(DETECTION_COLORS)})")

    top_samples: list[tuple[float, float]] = []
    side_samples: list[tuple[float, float] | None] = []
    estimated_top = 0
    detected_side = 0

    for i, sxy in enumerate(targets):
        # Verwachte camera-pixel positie via Phase 1 homography
        ex_n, ey_n = hm.apply_H(H_screen_to_cam, sxy[0], sxy[1])
        ex_top_px = (ex_n * w_top, ey_n * h_top)

        best_top = None
        best_top_score = 0
        best_side = None
        best_side_score = 0
        for color_name, color_bgr in DETECTION_COLORS:
            cv2.imshow(hm.CALIB_WIN,
                       _render_dot_in_color(display, sxy, color_bgr, dot_radius))
            cv2.waitKey(int(color_dwell_s * 1000))
            for _ in range(8):
                top_cap.grab()
                if side_cap:
                    side_cap.grab()
            ok, frame_top = top_cap.read()
            if not ok:
                continue
            res_top = _find_blob_in_diff(frame_top, baseline_top,
                                         ex_top_px, search_radius,
                                         diff_threshold, min_blob)
            if res_top is not None and res_top[2] > best_top_score:
                best_top_score = res_top[2]
                best_top = res_top
            if side_cap and baseline_side is not None:
                ok_s, frame_side = side_cap.read()
                if ok_s:
                    res_side = _find_blob_in_diff(frame_side, baseline_side,
                                                  None, None,
                                                  diff_threshold, min_blob)
                    if res_side is not None and res_side[2] > best_side_score:
                        best_side_score = res_side[2]
                        best_side = res_side

        if best_top is None:
            # Fallback: gebruik geschatte positie van Phase 1
            top_samples.append((ex_top_px[0] / w_top, ex_top_px[1] / h_top))
            estimated_top += 1
            if (i + 1) % 10 == 0 or i < 4:
                print(f"[multicolor] dot {i+1}/{len(targets)} — geschat (geen blob)")
        else:
            top_samples.append((best_top[0] / w_top, best_top[1] / h_top))

        if best_side is not None:
            side_samples.append((best_side[0], best_side[1]))
            detected_side += 1
        else:
            side_samples.append(None)

    # —— Eindscherm
    msg = [f"MULTI-KLEUR OK!", f"top: {len(targets)-estimated_top}/{len(targets)} exact"]
    if side_cap:
        msg.append(f"iPhone: {detected_side}/{len(targets)} dots gedetecteerd")
    cv2.imshow(hm.CALIB_WIN, hm._render_message(display, msg))
    cv2.waitKey(1500)
    hm.close_calib_overlay()
    print(f"\n[multicolor] klaar: top {len(targets)-estimated_top}/{len(targets)} exact, "
          f"iPhone {detected_side}/{len(targets)} bonus")
    return top_samples, side_samples


def _default_two_layer(frame_w: int, frame_h: int, table_y: int | None,
                        threshold: int) -> tuple[list[list[int]], list[list[int]]]:
    """Twee-laag default: bottom op tafelhoogte, top `threshold` px erboven.

    Beide polygons zijn rechthoeken die de hele framebreedte spannen en een
    smalle hoogte rond table_y. In side-view is het beamer-vlak typisch een
    dunne horizontale strip — de twee lagen zijn nagenoeg parallel.
    """
    if table_y is None:
        table_y = frame_h // 2
    lift = max(8, int(threshold))
    band = max(40, frame_h // 8)
    # Bottom (beamer-oppervlak): dunne band rond table_y (iets onder de lijn).
    bot_top = max(0, table_y - 4)
    bot_bot = min(frame_h - 1, table_y + band)
    bottom = [[10, bot_top], [frame_w - 10, bot_top],
              [frame_w - 10, bot_bot], [10, bot_bot]]
    # Top (1 cm boven): zelfde X-bounds, verschoven omhoog met `lift` px.
    top_top = max(0, bot_top - lift)
    top_bot = max(0, bot_bot - lift)
    top = [[10, top_top], [frame_w - 10, top_top],
           [frame_w - 10, top_bot], [10, top_bot]]
    return bottom, top


def phase_c_side_zone_editor(cap, frame_w: int, frame_h: int,
                             table_y: int | None, threshold: int,
                             initial_bottom: list[list[int]] | None = None,
                             initial_top: list[list[int]] | None = None,
                             ) -> tuple[list[list[int]], list[list[int]], int, int] | None:
    """Twee-laag side-zone editor.

    Beide polygons hebben 4 ankers (8 totaal sleepbaar):
      - BOTTOM (groen, ankers 1-4): beamer-oppervlak — vinger hier = touch
      - TOP    (oranje, ankers 5-8): 1 cm boven oppervlak — vinger erboven = te hoog

    Bediening:
      - klik & sleep op een anker → verplaats (8 totaal)
      - w / x → tafel-Y ±1   (verschuift visuele rode lijn)
      - + / - → threshold ±1 (= afstand tussen bottom en top bij reset)
      - r → reset beide polygons naar default
      - s → save & exit
      - q / ESC → annuleren (None retour)

    Returns: (bottom, top, table_y, threshold) bij save, None anders.
    """
    win = "Fase C — twee-laag touch-zone (sleep 8 ankers; s=save; q=quit)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    # Initialiseer twee polygonen.
    if initial_bottom is None or initial_top is None:
        default_bot, default_top = _default_two_layer(frame_w, frame_h, table_y, threshold)
        bottom = [list(p) for p in (initial_bottom or default_bot)]
        top = [list(p) for p in (initial_top or default_top)]
    else:
        bottom = [list(p) for p in initial_bottom]
        top = [list(p) for p in initial_top]

    state = {
        "dragging": -1,   # 0..3 = bottom anker, 4..7 = top anker, -1 = niets
        "table_y": table_y if table_y is not None else frame_h // 2,
        "threshold": max(6, int(threshold)),
    }
    hit_radius = 24

    def all_anchors() -> list[tuple[int, int, int]]:
        """Geeft (global_index, x, y) terug voor alle 8 ankers."""
        result = []
        for i, (ax, ay) in enumerate(bottom):
            result.append((i, ax, ay))
        for i, (ax, ay) in enumerate(top):
            result.append((i + 4, ax, ay))
        return result

    def set_anchor(global_i: int, x: int, y: int) -> None:
        if global_i < 4:
            bottom[global_i] = [x, y]
        else:
            top[global_i - 4] = [x, y]

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            best, best_d = -1, hit_radius
            for gi, ax, ay in all_anchors():
                d = ((ax - x) ** 2 + (ay - y) ** 2) ** 0.5
                if d < best_d:
                    best_d = d
                    best = gi
            state["dragging"] = best
        elif event == cv2.EVENT_MOUSEMOVE and state["dragging"] >= 0:
            set_anchor(state["dragging"], int(x), int(y))
        elif event == cv2.EVENT_LBUTTONUP:
            state["dragging"] = -1

    cv2.setMouseCallback(win, on_mouse)

    print("\n=== Fase C — twee-laag side-zone editor ===")
    print("  GROENE polygon (ankers 1-4) = beamer-oppervlak (touch hier)")
    print("  ORANJE polygon (ankers 5-8) = 1 cm boven oppervlak (ceiling)")
    print("  Sleep ankers met de muis. Touch = vinger tussen beide lagen.")
    print("  w = tafel-lijn omhoog   |   x = tafel-lijn omlaag")
    print("  +/- = threshold ±1 px (voor reset)")
    print("  r = reset beide polygons   |   s = save & exit   |   q/ESC = annuleren")

    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        overlay = frame.copy()

        bot_poly = np.array(bottom, dtype=np.int32).reshape(-1, 1, 2)
        top_poly = np.array(top, dtype=np.int32).reshape(-1, 1, 2)

        # Vul beide polygons licht (groen = bottom, oranje = top).
        mask = overlay.copy()
        cv2.fillPoly(mask, [bot_poly], (0, 80, 0))
        cv2.fillPoly(mask, [top_poly], (0, 60, 80))
        cv2.addWeighted(mask, 0.22, overlay, 0.78, 0, overlay)

        # Polygon-randen.
        cv2.polylines(overlay, [bot_poly], isClosed=True, color=(0, 220, 0), thickness=2)
        cv2.polylines(overlay, [top_poly], isClosed=True, color=(0, 165, 255), thickness=2)

        # Verbindingslijnen tussen overeenkomstige hoeken (3D-feel).
        for i in range(4):
            cv2.line(overlay,
                     (bottom[i][0], bottom[i][1]),
                     (top[i][0], top[i][1]),
                     (120, 120, 120), 1, cv2.LINE_AA)

        # Ankers tekenen + nummeren.
        for gi, ax, ay in all_anchors():
            is_bottom = gi < 4
            base_col = (0, 255, 255) if is_bottom else (60, 200, 255)
            col = (255, 255, 255) if state["dragging"] == gi else base_col
            cv2.circle(overlay, (ax, ay), hit_radius, col, 2)
            cv2.circle(overlay, (ax, ay), 4, col, -1)
            cv2.putText(overlay, str(gi + 1), (ax + 12, ay - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 1, cv2.LINE_AA)

        # Tafel-lijn (visueel referentie).
        ty = int(state["table_y"])
        th = int(state["threshold"])
        cv2.line(overlay, (0, ty), (frame_w, ty), (0, 0, 255), 1)
        cv2.putText(overlay, f"table_y={ty}",
                    (10, ty - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)

        # Statusbalk.
        cv2.rectangle(overlay, (0, frame_h - 36), (frame_w, frame_h), (0, 0, 0), -1)
        cv2.putText(overlay,
                    f"bottom=ankers 1-4 (groen)  top=ankers 5-8 (oranje)  "
                    f"table_y={ty}  threshold={th}  |  s=save  q=quit  r=reset",
                    (10, frame_h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

        cv2.imshow(win, overlay)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            cv2.destroyWindow(win)
            return None
        if key == ord("s"):
            cv2.destroyWindow(win)
            return bottom, top, state["table_y"], state["threshold"]
        if key == ord("r"):
            new_bot, new_top = _default_two_layer(
                frame_w, frame_h, state["table_y"], state["threshold"])
            bottom[:] = [list(p) for p in new_bot]
            top[:] = [list(p) for p in new_top]
        if key in (ord("+"), ord("=")):
            state["threshold"] = min(200, state["threshold"] + 1)
        elif key in (ord("-"), ord("_")):
            state["threshold"] = max(2, state["threshold"] - 1)
        elif key in (ord("w"), 82):
            state["table_y"] = max(0, state["table_y"] - 1)
        elif key in (ord("x"), 84):
            state["table_y"] = min(frame_h - 1, state["table_y"] + 1)


def phase_b_table(cap, landmarker):
    """Meet table_y_pixel en touch_threshold_px in de side-cam."""
    win = "Fase B — tafelvlak (side-cam)"
    log.info("Fase B: leg wijsvinger plat op tafel en houd vast")
    table = capture_hold(cap, landmarker, hold_secs=3.0,
                         prompt="Leg wijsvinger PLAT op tafel en houd vast",
                         win_title=win)
    if table is None:
        return None
    log.info("Fase B: til vinger ~1 cm op en houd vast")
    lift = capture_hold(cap, landmarker, hold_secs=3.0,
                        prompt="Til vinger ~1 cm omhoog en houd vast",
                        win_title=win)
    if lift is None:
        return None
    cv2.destroyWindow(win)
    table_y = int(round(table[1]))
    lift_y = int(round(lift[1]))
    delta = abs(table_y - lift_y)
    threshold = max(6, int(delta * 0.5))
    log.info("  table_y=%d  lift_y=%d  delta=%d → threshold=%dpx",
             table_y, lift_y, delta, threshold)
    return table_y, threshold


# ——— Main ——————————————————————————————————————————————————————————————
def main() -> int:
    parser = argparse.ArgumentParser(
        description="9×9 grid kalibratie + tafel-vlak meting voor dual-cam tracker.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--top-idx", type=int, default=3,
                        help="OpenCV index van de top-camera (iPhone Desk View via OBS).")
    parser.add_argument("--side-idx", type=int, default=0,
                        help="OpenCV index van de side-camera (DJI).")
    parser.add_argument("--display-idx", type=int, default=None,
                        help="0-based index van het scherm voor de dot-projectie "
                             "(default: hoofd-scherm, kies anders voor beamer).")
    parser.add_argument("--cols", type=int, default=hm.GRID_DEFAULT_COLS,
                        help="Aantal kolommen (1-9). 9 = maximale precisie.")
    parser.add_argument("--rows", type=int, default=hm.GRID_DEFAULT_ROWS,
                        help="Aantal rijen (1-9).")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL,
                        help="MediaPipe HandLandmarker model voor Fase B.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--skip-side", action="store_true",
                        help="Sla Fase B over (alleen top-cam grid kalibreren).")
    parser.add_argument("--mirror-x", action="store_true",
                        help="Spiegel cam-X (handig als top-cam je hand spiegelt).")
    parser.add_argument("--multicolor", action="store_true",
                        help="Fase A gebruikt multi-kleur dot-cycling (wit/geel/magenta/cyaan/"
                             "rood/groen) per positie. Helpt als de top-cam wit afvlakt. "
                             "Detecteert ook iPhone-grid als bonus.")
    parser.add_argument("--dot-radius", type=int, default=None,
                        help="Override dot-grootte in beamer-pixels. Default 33 (mono) of "
                             "60 (multicolor). Hoger = beter zichtbaar voor de top-cam.")
    parser.add_argument("--diff-threshold", type=int, default=15,
                        help="Min brightness-diff (0..255) om dot te detecteren. "
                             "Lager = vangt zwakkere signalen.")
    parser.add_argument("--min-blob", type=int, default=20,
                        help="Min blob-area in cam-pixels.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if not args.model.exists():
        log.error("MediaPipe model niet gevonden: %s", args.model)
        return 1

    # ——— Display kiezen ————————————————————————————————————————————————
    displays = hm.list_displays()
    if not displays:
        log.error("Geen schermen gedetecteerd via Quartz")
        return 1
    display = hm.pick_display(displays, args.display_idx)
    print(f"\n[disp] dot-projectie gaat op scherm: "
          f"{display['w']}x{display['h']} @ ({display['x']},{display['y']}) "
          f"main={display.get('main')}")
    if args.display_idx is None and len(displays) > 1:
        print("       Tip: gebruik --display-idx 1 om op de beamer (2e scherm) te projecteren")

    # ——— Fase A: top-cam grid kalibratie ————————————————————————————————
    mode_label = "multi-kleur" if args.multicolor else "wit"
    print(f"\n=== Fase A — top-camera grid ({args.cols}×{args.rows}, {mode_label}) ===")
    print(f"[cam] open top-cam index {args.top_idx}")
    top_cap = cv2.VideoCapture(args.top_idx, cv2.CAP_AVFOUNDATION)
    if not top_cap.isOpened():
        log.error("kan top-camera index %d niet openen", args.top_idx)
        return 1
    top_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    top_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    for _ in range(8):
        top_cap.grab()

    side_samples_grid: list[tuple[float, float] | None] = []
    if args.multicolor:
        # Open ook de side-cam zodat iPhone meedoet aan de dot-detectie.
        side_cap_grid = cv2.VideoCapture(args.side_idx, cv2.CAP_AVFOUNDATION)
        if side_cap_grid.isOpened():
            side_cap_grid.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            side_cap_grid.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            for _ in range(8):
                side_cap_grid.grab()
        else:
            side_cap_grid = None
            log.warning("side-cam %d niet beschikbaar tijdens Fase A — alleen top-cam",
                        args.side_idx)

        dot_radius = args.dot_radius if args.dot_radius is not None else 60
        res = phase_a_multicolor(
            top_cap, side_cap_grid, display,
            args.cols, args.rows,
            dot_radius=dot_radius,
            diff_threshold=args.diff_threshold,
            min_blob=args.min_blob,
        )
        if side_cap_grid is not None:
            side_cap_grid.release()
        top_cap.release()
        if res is None:
            log.error("Fase A multi-kleur mislukt")
            return 1
        samples, side_samples_grid = res
        cols, rows = args.cols, args.rows
    else:
        # Klassieke single-color via hand_mouse.auto_calibrate.
        if args.dot_radius is not None:
            hm.AUTO_CAL_DOT_RADIUS = args.dot_radius
        if args.diff_threshold != 15:
            hm.AUTO_CAL_DIFF_THRESH = args.diff_threshold
        if args.min_blob != 20:
            hm.AUTO_CAL_MIN_BLOB = args.min_blob
        samples, cols, rows = hm.auto_calibrate(
            top_cap, display, args.mirror_x, args.cols, args.rows
        )
        top_cap.release()

    if not samples:
        log.error("Fase A mislukt — kalibratie wordt niet opgeslagen")
        return 1
    print(f"[ok] Fase A: {len(samples)} dots gedetecteerd ({cols}×{rows})")
    if side_samples_grid:
        n_side = sum(1 for s in side_samples_grid if s is not None)
        print(f"     bonus: {n_side}/{len(side_samples_grid)} dots gezien door iPhone")

    # ——— Fase B + C: side-cam ——————————————————————————————————————————
    # Beide fases delen één side-cam VideoCapture en pre-existing JSON-laden
    # zodat een eerdere zone-editie behouden blijft als gebruiker Fase A
    # opnieuw doet maar Fase B/C overslaat.
    table_y: int | None = None
    threshold = 20
    zone_bottom: list[list[int]] | None = None
    zone_top: list[list[int]] | None = None
    if args.out.exists():
        try:
            existing = json.loads(args.out.read_text())
            zone_bottom = existing.get("side_zone_bottom") or None
            zone_top = existing.get("side_zone_top") or None
            # Backward compat: oude single-polygon → bottom + auto-gegenereerde top.
            if zone_bottom is None and existing.get("side_zone"):
                zone_bottom = existing["side_zone"]
            if existing.get("table_y_pixel") is not None:
                table_y = int(existing["table_y_pixel"])
                threshold = int(existing.get("touch_threshold_px", threshold))
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    if not args.skip_side:
        print(f"\n=== Fase B — side-camera tafelvlak (index {args.side_idx}) ===")
        side_cap = cv2.VideoCapture(args.side_idx, cv2.CAP_AVFOUNDATION)
        if not side_cap.isOpened():
            log.warning("kan side-camera %d niet openen — Fase B+C overgeslagen",
                        args.side_idx)
        else:
            side_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            side_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            for _ in range(8):
                side_cap.grab()

            # Fase B: tafel-meting via MediaPipe (vinger plat + 1 cm omhoog).
            side_lm = make_side_landmarker(args.model)
            res = phase_b_table(side_cap, side_lm)
            side_lm.close()
            if res is None:
                log.warning("Fase B overgeslagen of geannuleerd "
                            "— Fase C gebruikt vorige waarden")
            else:
                table_y, threshold = res

            # Fase C: interactieve twee-laag zone-editor. Side-cam blijft open.
            ok, sample_frame = side_cap.read()
            if ok:
                side_h, side_w = sample_frame.shape[:2]
                editor_res = phase_c_side_zone_editor(
                    side_cap, side_w, side_h, table_y, threshold,
                    initial_bottom=zone_bottom,
                    initial_top=zone_top,
                )
                if editor_res is None:
                    print("[!] Fase C geannuleerd — vorige zone (indien aanwezig) blijft.")
                else:
                    bot_new, top_new, table_y_new, threshold_new = editor_res
                    zone_bottom = bot_new
                    zone_top = top_new
                    table_y = int(table_y_new)
                    threshold = int(threshold_new)
                    print(f"[ok] Fase C: bottom={len(zone_bottom)} ankers, "
                          f"top={len(zone_top)} ankers, "
                          f"table_y={table_y}, threshold={threshold}")
            side_cap.release()

    # ——— Opslaan ——————————————————————————————————————————————————————
    out_data = {
        "samples": samples,
        "cols": cols,
        "rows": rows,
        "mirror_x": args.mirror_x,
        "table_y_pixel": table_y,
        "touch_threshold_px": threshold,
        "side_zone_bottom": zone_bottom,
        "side_zone_top": zone_top,
        # iPhone-grid samples uit Fase A (alleen met --multicolor).
        # Bevat per dot een [x,y] pixel-positie waar iPhone hem zag, of null.
        "side_samples_grid": side_samples_grid if side_samples_grid else None,
        "screen_w": display["w"],
        "screen_h": display["h"],
        "screen_x": display["x"],
        "screen_y": display["y"],
        "top_camera_index": args.top_idx,
        "side_camera_index": args.side_idx,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    args.out.write_text(json.dumps(out_data, indent=2))
    print(f"\n[ok] Opgeslagen: {args.out}")
    print(f"     Fase A: {len(samples)} samples in {cols}×{rows} grid")
    print(f"     Fase B: table_y={table_y}  threshold={threshold}px")
    if zone_bottom and zone_top:
        print(f"     Fase C: bottom={len(zone_bottom)} ankers, "
              f"top={len(zone_top)} ankers")
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
