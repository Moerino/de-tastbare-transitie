#!/usr/bin/env python3
"""
Hand -> macOS cursor.

Pipeline:
  DJI Action 5 Pro (or any webcam)
    -> OpenCV frame
    -> MediaPipe GestureRecognizer (Tasks API)
    -> 21 hand landmarks + categorical gesture (Closed_Fist, Open_Palm, ...)
    -> position scaling (4-point homography, calibrated on-screen)
    -> PyAutoGUI
    -> macOS system cursor

Gesture: Closed_Fist -> mouse button pressed (click & drag).
Outside-zone gate: when the hand maps outside the 4-corner calibration zone,
the cursor stays put (we ignore the input).

Hotkeys (preview window):
  c    start on-screen 4-point calibration on the controlled display
  esc  cancel calibration
  m    toggle horizontal mirror
  d    cycle which display the cursor controls
  q    quit
"""

import argparse
import json
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

import pyautogui
import Quartz

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

# ---------- Config ----------------------------------------------------------
HERE = Path(__file__).resolve().parent
CALIB_PATH = HERE / "calibration.json"
MODEL_PATH = HERE / "gesture_recognizer.task"

# Cursor behaviour
SMOOTHING            = 0.55
MOVE_DEADZONE_PX     = 1
MIRROR_X_DEFAULT     = False    # camera shows world as-is (not flipped) by default
ZONE_MARGIN          = 0.04     # allow this much overshoot beyond [0,1] before flagging out-of-zone
CURSOR_OFFSET_ROWS   = 2.0      # cursor sits this many grid-rows ABOVE the hand
                                #   (so your hand doesn't block the projection where the cursor is).
                                #   Set to 0 to disable. Press 'o' at runtime to cycle 0/1/2/3 rows.

# Calibration grid (cols × rows = total points). Default 3×3 → 9 points → 4 sub-cells.
# More points = better correction of beamer/lens distortion (curved edges).
GRID_DEFAULT_COLS = 3
GRID_DEFAULT_ROWS = 3
GRID_MIN_DIM      = 2
GRID_MAX_DIM      = 9

# Gesture / fist click stability
FIST_VOTE_WINDOW = 5    # frames to look at
FIST_VOTE_DOWN   = 3    # ≥ this many Closed_Fist in window -> click down
FIST_VOTE_UP     = 1    # ≤ this many Closed_Fist in window -> click up
FIST_FREEZE_FRAMES = 10 # require this many CONSECUTIVE fist frames before freezing
DRAG_DEADZONE_PX = 40   # tijdens een ingedrukte klik blijft de cursor bevroren op het
                        # klikpunt; pas als je verder dan dit beweegt wordt het slepen
                        # (zo wordt een klik nooit per ongeluk een sleepbeweging).
                        # the cursor (avoids freezing on single-frame false positives).
                        # ~10 frames ≈ 1/3 sec at 30 fps. Decoupled from the click
                        # vote window above.

# Calibration overlay layout (in display pixels)
CALIB_MARGIN       = 60    # distance of marker from screen edge
CALIB_RADIUS       = 38
CALIB_HOLD_SECS    = 3.0   # hold fist over a corner this long to capture
CALIB_COOLDOWN_SEC = 2.0   # rest period after capture before next corner is armed

# MediaPipe landmarks
LM_PALM      = 9
LM_WRIST     = 0
LM_THUMB_TIP = 4
LM_INDEX_TIP = 8
# Stable anchor: wrist + 4 finger MCP joints. These knuckles barely move when
# fingers curl, so averaging them gives a far steadier hand position than just
# the palm landmark (which shifts as the hand closes into a fist).
LM_ANCHOR    = [0, 5, 9, 13, 17]
# Finger (TIP, MCP) pairs for curl detection (non-thumb)
FINGER_TIP_MCP = [(8, 5), (12, 9), (16, 13), (20, 17)]
# Curl ratio threshold: a finger is "curled" when dist(TIP,WRIST) < CURL_RATIO * dist(MCP,WRIST)
CURL_RATIO         = 1.30
FIST_FINGERS_NEEDED = 3   # of 4 non-thumb fingers curled -> fist
# Pinch threshold: thumb-tip to index-tip 3D distance / palm size.
# Touching fingers -> ratio ~0.1-0.3. Extended -> ratio ~1.5-2.5.
PINCH_RATIO        = 0.40

# Preview window + mouse-drag editing
PREVIEW_WIN  = "Hand Mouse - Preview"
DRAG_HIT_PX  = 28          # click within this many pixels of a corner to grab it
def default_grid_samples(cols, rows, inset=0.15):
    """Returns rows*cols points in row-major order, spread in a regular grid
    between [inset, 1-inset] in both axes."""
    pts = []
    for r in range(rows):
        for c in range(cols):
            cx = inset + (1 - 2*inset) * (c / max(1, cols - 1))
            cy = inset + (1 - 2*inset) * (r / max(1, rows - 1))
            pts.append((cx, cy))
    return pts

# Mouse interaction state shared with the OpenCV mouse callback
mouse_state = {
    "pos": (0, 0),
    "dragging": None,   # 0..3 corner index being dragged, or None
    "hover": None,      # 0..3 corner index near mouse, or None
    "frame_w": 1, "frame_h": 1,
    "samples": None,    # in-place reference to calib_samples list
    "needs_save": False,
}

def on_mouse(event, x, y, flags, param):
    state = param
    state["pos"] = (x, y)
    samples = state["samples"]
    if samples is None:
        return
    w = max(1, state["frame_w"]); h = max(1, state["frame_h"])

    # Find nearest corner within hit radius for hover/drag detection
    nearest = None; nearest_d = DRAG_HIT_PX + 1
    for i, s in enumerate(samples):
        if s is None: continue
        sx = s[0] * w; sy = s[1] * h
        d = ((x - sx) ** 2 + (y - sy) ** 2) ** 0.5
        if d < nearest_d:
            nearest_d = d; nearest = i
    state["hover"] = nearest

    if event == cv2.EVENT_LBUTTONDOWN:
        if nearest is not None:
            state["dragging"] = nearest
    elif event == cv2.EVENT_MOUSEMOVE and state["dragging"] is not None:
        i = state["dragging"]
        nx = max(0.0, min(1.0, x / w))
        ny = max(0.0, min(1.0, y / h))
        samples[i] = (nx, ny)
    elif event == cv2.EVENT_LBUTTONUP:
        if state["dragging"] is not None:
            state["dragging"] = None
            state["needs_save"] = True

HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (5,9),(9,10),(10,11),(11,12),
    (9,13),(13,14),(14,15),(15,16),
    (13,17),(17,18),(18,19),(19,20),
    (0,17),
]

# ---------- Display helpers -------------------------------------------------
def list_displays():
    err, ids, n = Quartz.CGGetActiveDisplayList(16, None, None)
    out = []
    for did in ids[:n]:
        b = Quartz.CGDisplayBounds(did)
        out.append({
            "id": int(did),
            "x": int(b.origin.x), "y": int(b.origin.y),
            "w": int(b.size.width), "h": int(b.size.height),
            "main": bool(Quartz.CGDisplayIsMain(did)),
        })
    return out

def pick_display(displays, requested):
    if requested is not None:
        return displays[max(0, min(requested, len(displays) - 1))]
    for d in displays:
        if not d["main"]:
            return d
    return displays[0]

# ---------- Calibration math ------------------------------------------------
def compute_homography_4pt(src, dst):
    """Solve 3x3 homography mapping 4 src points -> 4 dst points."""
    A, b = [], []
    for (sx,sy),(dx,dy) in zip(src, dst):
        A.append([sx,sy,1,0,0,0,-sx*dx,-sy*dx]); b.append(dx)
        A.append([0,0,0,sx,sy,1,-sx*dy,-sy*dy]); b.append(dy)
    A = np.array(A, dtype=np.float64); b = np.array(b, dtype=np.float64)
    try:
        h = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        h, *_ = np.linalg.lstsq(A, b, rcond=None)
    return np.array([[h[0],h[1],h[2]],[h[3],h[4],h[5]],[h[6],h[7],1.0]])

def apply_H(H, x, y):
    v = H @ np.array([x, y, 1.0], dtype=np.float64)
    if abs(v[2]) < 1e-9: return 0.0, 0.0
    return float(v[0]/v[2]), float(v[1]/v[2])

def compute_grid_cells(samples, cols, rows):
    """For an N×M grid of points returns (cells, outer_H):
      - cells: list of (quad_np, H) per (cols-1)*(rows-1) sub-cell, each H mapping
        the cell's camera-space quad to its sub-rectangle of unit screen-space.
      - outer_H: single 4-corner homography from the OUTER quad of the grid to [0,1]^2.
        Used as fallback when the hand is outside every cell (so we can extrapolate,
        e.g. when the cursor is offset upward and the hand goes below the zone)."""
    cells = []
    outer_H = np.eye(3, dtype=np.float64)
    if cols < 2 or rows < 2: return cells, outer_H
    for r in range(rows - 1):
        for c in range(cols - 1):
            tl = samples[r*cols + c]
            tr = samples[r*cols + c+1]
            br = samples[(r+1)*cols + c+1]
            bl = samples[(r+1)*cols + c]
            src = [tl, tr, br, bl]
            sx0 = c / (cols - 1); sx1 = (c + 1) / (cols - 1)
            sy0 = r / (rows - 1); sy1 = (r + 1) / (rows - 1)
            dst = [(sx0, sy0), (sx1, sy0), (sx1, sy1), (sx0, sy1)]
            H = compute_homography_4pt(src, dst)
            quad = np.array(src, dtype=np.float32)
            cells.append((quad, H))
    outer = [
        samples[0],                              # TL
        samples[cols - 1],                       # TR
        samples[(rows - 1) * cols + cols - 1],   # BR
        samples[(rows - 1) * cols],              # BL
    ]
    outer_H = compute_homography_4pt(outer, [(0, 0), (1, 0), (1, 1), (0, 1)])
    return cells, outer_H

# ---------- Auto-calibration (structured-light) ----------------------------
AUTO_CAL_DOT_RADIUS    = 33    # bright dot radius on projector (px) — small dots, less neighbour overlap at dense grids
AUTO_CAL_DIFF_THRESH   = 25    # min brightness diff (0..255) to count as the dot
AUTO_CAL_MIN_BLOB      = 20    # min blob area (camera pixels) to accept — scaled for smaller dots
AUTO_CAL_SETTLE_FRAMES = 18    # frames to throw away after projector update (drain buffer)
AUTO_CAL_FRAME_GRACE_S = 0.90  # show dot this long before capturing (30 fps -> ~27 frames)
AUTO_CAL_POST_HOLD_S   = 0.15  # keep dot on briefly after capture, so projector doesn't flicker
AUTO_CAL_MAX_GRID      = 9     # auto-cal supports up to 9×9 = 81 points
AUTO_CAL_SEARCH_FRAC   = 0.20  # accept blobs within this fraction of the projection size from expected
                                # (auto-tightened for denser grids to avoid neighbour confusion)

def _render_black(display):
    return np.zeros((display["h"], display["w"], 3), dtype=np.uint8)

def _render_message(display, lines, sub=None):
    img = _render_black(display)
    W, H = display["w"], display["h"]
    for i, line in enumerate(lines):
        (tw, th), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 1.4, 3)
        cv2.putText(img, line, (W//2 - tw//2, H//2 + i*60 - 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3, cv2.LINE_AA)
    if sub:
        (tw, th), _ = cv2.getTextSize(sub, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.putText(img, sub, (W//2 - tw//2, H - 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (180, 180, 180), 2, cv2.LINE_AA)
    return img

def _render_dot(display, screen_xy_norm, idx, total):
    img = _render_black(display)
    W, H = display["w"], display["h"]
    cx = int(screen_xy_norm[0] * W)
    cy = int(screen_xy_norm[1] * H)
    # white dot with a small dim ring around for orientation
    cv2.circle(img, (cx, cy), AUTO_CAL_DOT_RADIUS, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.putText(img, f"{idx+1}/{total}", (20, H - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (90, 90, 90), 2, cv2.LINE_AA)
    return img

def _capture(cap, mirror_x, drain=0):
    """Read a single frame, draining `drain` first to flush camera buffers."""
    for _ in range(drain):
        cap.grab()
    ok, frame = cap.read()
    if not ok:
        return None
    if mirror_x:
        frame = cv2.flip(frame, 1)
    return frame

def _expected_dot_positions(cols, rows, inset=0.0):
    """Where each grid point lives in projector screen-space (0..1, 0..1).
    inset=0 means the outermost dots sit at the very edges of the projection
    (their visible disc is clipped to the screen corner/edge but the centroid
    still lines up well enough for calibration)."""
    pts = []
    for r in range(rows):
        for c in range(cols):
            x = inset + (1 - 2*inset) * (c / max(1, cols - 1))
            y = inset + (1 - 2*inset) * (r / max(1, rows - 1))
            pts.append((x, y))
    return pts

def _detect_dot(cap, display, mirror_x, baseline, screen_xy, idx, total, expected_px=None, search_radius=None):
    """Show a single dot, capture, diff against baseline, return (cx, cy) in
    camera pixels — or None on failure. If expected_px+search_radius given,
    only accept blobs near that point."""
    cv2.imshow(CALIB_WIN, _render_dot(display, screen_xy, idx, total))
    # Wait + drain camera buffer so we get a FRESH frame of the new dot.
    # At 30 fps, 0.9s = ~27 frames of dot-on time before we grab.
    cv2.waitKey(int(AUTO_CAL_FRAME_GRACE_S * 1000))
    for _ in range(AUTO_CAL_SETTLE_FRAMES): cap.grab()
    frame_on = _capture(cap, mirror_x)
    # Keep the dot visible just a hair longer so the projector isn't already
    # blanking when the next capture round starts (reduces ghosting).
    cv2.waitKey(int(AUTO_CAL_POST_HOLD_S * 1000))
    if frame_on is None:
        return None, "camera dropped frame"

    diff = cv2.absdiff(frame_on, baseline)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (9, 9), 0)
    _, mask = cv2.threshold(gray, AUTO_CAL_DIFF_THRESH, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, "no bright region"

    # Score candidates: prefer biggest blob, but if we have an expected point,
    # require closeness and prefer closest.
    candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < AUTO_CAL_MIN_BLOB: continue
        M = cv2.moments(cnt)
        if M["m00"] == 0: continue
        cx = M["m10"] / M["m00"]
        cy = M["m01"] / M["m00"]
        candidates.append((cx, cy, area))

    if not candidates:
        return None, "no blob large enough"

    if expected_px is not None and search_radius is not None:
        ex, ey = expected_px
        # Filter to those within radius
        near = [(c, ((c[0]-ex)**2 + (c[1]-ey)**2) ** 0.5) for c in candidates]
        near = [(c, d) for (c, d) in near if d <= search_radius]
        if not near:
            return None, f"no blob within {int(search_radius)}px of expected"
        # Pick the closest (in case of multiple)
        near.sort(key=lambda x: x[1])
        best = near[0][0]
    else:
        # No expectation: pick the largest blob
        candidates.sort(key=lambda c: -c[2])
        best = candidates[0]

    return (best[0], best[1]), None

def auto_calibrate(cap, display, mirror_x, cols, rows):
    """Run two-phase structured-light calibration. Returns (samples, cols, rows)
    where cols/rows may have been reduced from input. Or (None, cols, rows) on failure.

    Phase 1: project 4 outer corner dots, detect them globally (largest blob).
             Build a rough screen->camera homography.
    Phase 2: for each grid point (≤ AUTO_CAL_MAX_GRID), compute expected camera
             position via Phase-1 homography, then accept only blobs nearby.
    """
    # Always cap at 3x3 for auto-cal reliability
    cols = min(cols, AUTO_CAL_MAX_GRID)
    rows = min(rows, AUTO_CAL_MAX_GRID)
    cols = max(cols, GRID_MIN_DIM); rows = max(rows, GRID_MIN_DIM)
    if cols * rows < 4:
        cols = rows = 2

    open_calib_overlay(display)
    AUTO_CAL_COUNTDOWN_S = 10
    for sec in range(AUTO_CAL_COUNTDOWN_S, 0, -1):
        cv2.imshow(CALIB_WIN, _render_message(display,
                        ["AUTO-KALIBRATIE", f"Verlaat het beeld... {sec}"],
                        sub="Houd de DJI stil. Druk ESC om te annuleren."))
        t_end = time.time() + 1.0
        while time.time() < t_end:
            if (cv2.waitKey(20) & 0xFF) == 27:
                close_calib_overlay(); return None, cols, rows

    # Baseline frame (black projection)
    cv2.imshow(CALIB_WIN, _render_message(display, ["Bezig met meten..."]))
    cv2.waitKey(120)
    cv2.imshow(CALIB_WIN, _render_black(display))
    cv2.waitKey(int(AUTO_CAL_FRAME_GRACE_S * 1000))
    for _ in range(AUTO_CAL_SETTLE_FRAMES + 5): cap.grab()
    baseline = _capture(cap, mirror_x)
    if baseline is None:
        close_calib_overlay(); print("[auto-calib] no camera frame"); return None, cols, rows
    h, w = baseline.shape[:2]

    # --- Phase 1: detect the 4 outer corners globally ---------------------
    # Place corner dots at the very edges of the projection so the
    # calibrated zone reaches the actual screen edge.
    print("[auto-calib] phase 1: detecting 4 outer corners (edge-aligned)")
    inset = 0.0
    corner_screen = [
        (inset, inset),                  # TL
        (1 - inset, inset),              # TR
        (1 - inset, 1 - inset),          # BR
        (inset, 1 - inset),              # BL
    ]
    corner_cam = []
    for i, sxy in enumerate(corner_screen):
        pos, err = _detect_dot(cap, display, mirror_x, baseline, sxy, i, 4)
        if pos is None:
            print(f"[auto-calib] phase 1 corner {i+1}/4 failed: {err}")
            cv2.imshow(CALIB_WIN, _render_message(display,
                ["KALIBRATIE MISLUKT", f"Hoek {i+1} niet gevonden", err or ""],
                sub="Maak de kamer donkerder of richt de camera anders."))
            cv2.waitKey(1800); close_calib_overlay()
            return None, cols, rows
        corner_cam.append(pos)
        print(f"[auto-calib] phase 1 corner {i+1}/4 -> cam ({pos[0]/w:.3f}, {pos[1]/h:.3f})")

    # Build a rough screen->camera homography from these 4 points
    src_screen = corner_screen
    dst_cam = [(p[0]/w, p[1]/h) for p in corner_cam]
    H_screen_to_cam = compute_homography_4pt(src_screen, dst_cam)

    # Estimate projection size in the camera image (for search radius).
    # For dense grids the cell size shrinks, so cap the search at ~0.7 cell width
    # — enough wiggle room for perspective skew without grabbing the neighbour.
    proj_diag = ((corner_cam[2][0] - corner_cam[0][0]) ** 2 +
                 (corner_cam[2][1] - corner_cam[0][1]) ** 2) ** 0.5
    cell_cap = 0.7 * proj_diag / max(cols, rows)
    search_radius = max(35, min(AUTO_CAL_SEARCH_FRAC * proj_diag, cell_cap))

    # --- Phase 2: detect each grid point with expected-position filtering ---
    print(f"[auto-calib] phase 2: detecting {cols}×{rows}={cols*rows} grid points (search radius {int(search_radius)}px)")
    targets = _expected_dot_positions(cols, rows)
    samples = []
    estimated = []  # indices that used Phase-1 estimate as fallback
    for i, sxy in enumerate(targets):
        # Expected camera pixel position via rough homography
        ex_n, ey_n = apply_H(H_screen_to_cam, sxy[0], sxy[1])
        ex_px, ey_px = ex_n * w, ey_n * h

        # First try: normal search radius
        pos, err = _detect_dot(cap, display, mirror_x, baseline, sxy, i, len(targets),
                                expected_px=(ex_px, ey_px), search_radius=search_radius)
        # Retry once with a larger radius if it failed (helps near projection edges /
        # where camera autoexposure drifted)
        if pos is None:
            print(f"[auto-calib] dot {i+1} miss ({err}) — retry with wider radius")
            time.sleep(0.3)
            pos, err = _detect_dot(cap, display, mirror_x, baseline, sxy, i, len(targets),
                                    expected_px=(ex_px, ey_px),
                                    search_radius=search_radius * 1.8)
        # Last resort: use the rough Phase-1 estimate so calibration completes.
        # Final cells will be slightly off in this region but the rest is fine.
        if pos is None:
            print(f"[auto-calib] dot {i+1} undetectable — using estimated position from Phase 1")
            pos = (ex_px, ey_px)
            estimated.append(i + 1)

        samples.append((pos[0] / w, pos[1] / h))
        if (i + 1) not in estimated:
            print(f"[auto-calib] dot {i+1}/{len(targets)} -> cam ({pos[0]/w:.3f}, {pos[1]/h:.3f})  expected=({ex_n:.3f}, {ey_n:.3f})")

    # Refresh baseline periodically? For now, just refresh the rough homography
    # using the four corners of the actual detected grid (more accurate than Phase 1)
    if cols >= 2 and rows >= 2 and not estimated:
        corner_idx = [0, cols-1, rows*cols-1, (rows-1)*cols]
        better_corners = [samples[i] for i in corner_idx]
        H_screen_to_cam = compute_homography_4pt(
            [(0,0),(1,0),(1,1),(0,1)], better_corners)
        # (kept for potential future refinement passes)

    if estimated:
        msg = [f"KALIBRATIE OK ({cols}×{rows})", f"{len(estimated)} van {cols*rows} stippen geschat",
               "(rest is exact gemeten)"]
        print(f"[auto-calib] WARNING: estimated {len(estimated)} dots: {estimated}")
    else:
        msg = ["KALIBRATIE OK!", f"{cols}×{rows} grid", "alle stippen exact"]
    cv2.imshow(CALIB_WIN, _render_message(display, msg))
    cv2.waitKey(1200)
    close_calib_overlay()
    return samples, cols, rows

def apply_grid(cells, outer_H, x, y):
    """Returns (sx, sy) in screen-space normalized coords. Always returns a result:
    inside any cell we use that cell's precise H (good for curve correction);
    outside all cells we extrapolate via outer_H. The caller decides what counts
    as in-zone using the returned coords."""
    pt = (float(x), float(y))
    for (quad, H) in cells:
        if cv2.pointPolygonTest(quad, pt, False) >= 0:
            return apply_H(H, x, y)
    return apply_H(outer_H, x, y)

def load_calibration():
    """Returns (samples, cols, rows). If file missing/invalid, returns ([], cols, rows)."""
    if not CALIB_PATH.exists():
        return [], GRID_DEFAULT_COLS, GRID_DEFAULT_ROWS
    try:
        data = json.loads(CALIB_PATH.read_text())
        samples = [tuple(p) if p is not None else None for p in data.get("samples", [])]
        cols = int(data.get("cols", GRID_DEFAULT_COLS))
        rows = int(data.get("rows", GRID_DEFAULT_ROWS))
        # Backward compatibility: old format had exactly 4 points and no cols/rows.
        if "cols" not in data and len(samples) == 4:
            cols, rows = 2, 2
        return samples, cols, rows
    except Exception as e:
        print(f"[calib] load failed: {e}")
        return [], GRID_DEFAULT_COLS, GRID_DEFAULT_ROWS

def save_calibration(samples, cols, rows, mirror_x):
    data = {
        "samples": [list(s) if s is not None else None for s in samples],
        "cols": cols, "rows": rows,
        "mirror_x": mirror_x,
    }
    CALIB_PATH.write_text(json.dumps(data, indent=2))
    print(f"[calib] saved -> {CALIB_PATH}  ({cols}×{rows}={len(samples)} points)")

# ---------- Manual fist detection (camera-angle independent) ---------------
def fist_score_from_landmarks(lm):
    """Return (curled_count, ratios) — curled_count is 0..4 (non-thumb fingers).
    Uses 3D distances so it works regardless of camera angle (palm side, back side,
    sideways)."""
    def d(a, b):
        return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2) ** 0.5
    wrist = lm[LM_WRIST]
    curled = 0
    ratios = []
    for tip_i, mcp_i in FINGER_TIP_MCP:
        d_tip = d(lm[tip_i], wrist)
        d_mcp = d(lm[mcp_i], wrist)
        r = d_tip / d_mcp if d_mcp > 1e-6 else 0.0
        ratios.append(r)
        if r < CURL_RATIO:
            curled += 1
    return curled, ratios

def is_fist(lm, gesture_label):
    """Combine manual detection with GestureRecognizer label."""
    curled, _ = fist_score_from_landmarks(lm)
    return curled >= FIST_FINGERS_NEEDED or gesture_label == "Closed_Fist"

def pinch_score(lm):
    """Return (is_pinch, ratio).
    Ratio = 3D dist(thumb_tip, index_tip) / dist(wrist, palm). Low = pinching.
    Hand-orientation independent because it normalizes by palm size."""
    def d3(a, b):
        return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2) ** 0.5
    palm_size = d3(lm[LM_WRIST], lm[LM_PALM]) or 1e-6
    pinch_d = d3(lm[LM_THUMB_TIP], lm[LM_INDEX_TIP])
    ratio = pinch_d / palm_size
    return ratio < PINCH_RATIO, ratio

# ---------- Camera ---------------------------------------------------------
def open_camera(forced_index):
    indices = [forced_index] if forced_index is not None else list(range(5))
    for idx in indices:
        cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            ok, _ = cap.read()
            if ok:
                print(f"[cam] using index {idx}")
                return cap
            cap.release()
    return None

# ---------- Preview drawing -----------------------------------------------
def draw_preview(frame, landmarks, gesture_name, ctx):
    h, w = frame.shape[:2]

    # Draw the calibrated N×M grid mesh in camera space.
    samples = ctx.get("calib_samples") or []
    cols = ctx.get("grid_cols", 2)
    rows = ctx.get("grid_rows", 2)
    hover_idx = ctx.get("mouse_hover")
    drag_idx  = ctx.get("mouse_drag")
    expected = cols * rows
    have_full = len(samples) == expected and all(s is not None for s in samples)

    if have_full:
        pix = [(int(s[0] * w), int(s[1] * h)) for s in samples]
        # Translucent fill of the outer polygon (TL, TR, BR, BL)
        outer_idx = [0, cols - 1, rows * cols - 1, (rows - 1) * cols]
        outer = np.array([pix[i] for i in outer_idx], dtype=np.int32)
        overlay = frame.copy()
        cv2.fillPoly(overlay, [outer], (0, 180, 100))
        cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)

        # Horizontal lines (each row)
        for r in range(rows):
            pts = [pix[r * cols + c] for c in range(cols)]
            for i in range(len(pts) - 1):
                cv2.line(frame, pts[i], pts[i+1], (0, 220, 120), 2, cv2.LINE_AA)
        # Vertical lines (each col)
        for c in range(cols):
            pts = [pix[r * cols + c] for r in range(rows)]
            for i in range(len(pts) - 1):
                cv2.line(frame, pts[i], pts[i+1], (0, 220, 120), 2, cv2.LINE_AA)

        # Point handles
        for i, (cx_pt, cy_pt) in enumerate(pix):
            if drag_idx == i:
                col = (40, 90, 255); rad = 14
            elif hover_idx == i:
                col = (0, 220, 255); rad = 12
            else:
                col = (0, 220, 120); rad = 7
            cv2.circle(frame, (cx_pt, cy_pt), rad+2, col, 2, cv2.LINE_AA)
            cv2.circle(frame, (cx_pt, cy_pt), max(1, rad-3), col, -1, cv2.LINE_AA)

    # During calibration, also highlight which corner is next with a yellow target.
    if ctx.get("calib_active") and ctx["calib_corner"] < 4:
        # We don't yet know where the *next* corner is in camera-space — that's what we're capturing.
        # Helpful hint: if at least one corner is captured, draw an arrow from
        # the centroid of captured points to a guessed direction (just visual nudge).
        pass

    if landmarks:
        pts = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]
        for a, b in HAND_CONNECTIONS:
            cv2.line(frame, pts[a], pts[b], (255, 255, 255), 2)
        for x, y in pts:
            cv2.circle(frame, (x, y), 4, (0, 255, 255), -1)
        cv2.circle(frame, pts[LM_PALM], 8, (255, 0, 255), 2)

    # Mark the palm landmark with green ring when fist-down, red when in-zone, grey otherwise.
    if landmarks:
        palm_px = int(landmarks[LM_PALM].x * w)
        palm_py = int(landmarks[LM_PALM].y * h)
        if ctx["fist_down"]:
            ring = (0, 255, 80)
        elif ctx["in_zone"]:
            ring = (80, 80, 255)
        else:
            ring = (140, 140, 140)
        cv2.circle(frame, (palm_px, palm_py), 18, ring, 3, cv2.LINE_AA)

    curl_str = ""
    if ctx.get("curled") is not None:
        curl_str = f"  curled={ctx['curled']}/4"
    pinch_str = ""
    if ctx.get("pinch_ratio") is not None:
        flag = "YES" if ctx.get("pinch_now") else "no"
        pinch_str = f"  pinch={flag} (r={ctx['pinch_ratio']:.2f}, thresh<{PINCH_RATIO})"
    cols = ctx.get('grid_cols', 2); rows = ctx.get('grid_rows', 2)
    hud_lines = [
        f"display: #{ctx['display_idx']+1}  {ctx['display']['w']}x{ctx['display']['h']}  main={ctx['display']['main']}",
        f"click: pinch OR fist     fist_down: {ctx['fist_down']}    in_zone: {ctx['in_zone']}",
        f"gesture: {gesture_name or '-'}{curl_str}{pinch_str}",
        f"mirror_x: {ctx['mirror_x']}    smoothing: {SMOOTHING}    grid: {cols}x{rows}",
        "a = AUTO-CALIBRATE (project dots, detect with camera)",
        "or DRAG points with mouse to align mesh manually",
        "keys: +/- grid size   r=reset   m=mirror   d=display   q=quit",
    ]
    y0 = h - 10
    for i, line in enumerate(reversed(hud_lines)):
        cv2.putText(frame, line, (10, y0 - 18*i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1, cv2.LINE_AA)

    if ctx["calib_active"]:
        cv2.rectangle(frame, (0,0), (w, 40), (0,0,0), -1)
        cd = ctx.get("calib_cooldown_left", 0.0) or 0.0
        if cd > 0:
            txt = f"COOLDOWN  {cd:.1f}s — verplaats hand naar hoek {ctx['calib_corner']+1}/4"
        else:
            txt = f"CALIBRATING  hoek {ctx['calib_corner']+1}/4 — hand op de oplichtende hoek + vuist ({int(CALIB_HOLD_SECS)}s)"
        cv2.putText(frame, txt, (10, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,200,255), 1, cv2.LINE_AA)

    cv2.imshow(PREVIEW_WIN, frame)

# ---------- Calibration overlay (on the controlled display) ----------------
CALIB_WIN = "Hand Mouse - Calibration"
calib_overlay_open = [False]  # mutable flag

def open_calib_overlay(display):
    cv2.namedWindow(CALIB_WIN, cv2.WINDOW_NORMAL)
    cv2.moveWindow(CALIB_WIN, display["x"], display["y"])
    cv2.resizeWindow(CALIB_WIN, display["w"], display["h"])
    # Try real fullscreen; on macOS this may or may not lock to current display
    try:
        cv2.setWindowProperty(CALIB_WIN, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    except Exception:
        pass
    calib_overlay_open[0] = True

def close_calib_overlay():
    if calib_overlay_open[0]:
        try: cv2.destroyWindow(CALIB_WIN)
        except Exception: pass
        calib_overlay_open[0] = False

def _draw_arrow(img, p_from, p_to, color, thickness=8, tip_size=40):
    """Draw a thick arrow from p_from to p_to. tip_size in pixels."""
    p_from = (int(p_from[0]), int(p_from[1]))
    p_to   = (int(p_to[0]),   int(p_to[1]))
    # Shorten arrow so the tip doesn't punch into the target circle
    import math
    dx, dy = p_to[0]-p_from[0], p_to[1]-p_from[1]
    L = max(1.0, math.hypot(dx, dy))
    shrink = min(L * 0.18, 90)
    p_to_short = (int(p_to[0] - dx/L*shrink), int(p_to[1] - dy/L*shrink))
    cv2.arrowedLine(img, p_from, p_to_short, color, thickness, cv2.LINE_AA, tipLength=tip_size/L)

def render_calib_overlay(display, corner_idx, hold_pct, hand_screen_pos, counting, cooldown_left):
    """Draw the calibration screen with 4 corner targets, highlight active.
    `hold_pct` = 0..1, fraction of CALIB_HOLD_SECS elapsed.
    `counting` = True when a fist is currently held (countdown active).
    `cooldown_left` = seconds of post-capture cooldown remaining (0 = none).
    """
    W, H = display["w"], display["h"]
    img = np.zeros((H, W, 3), dtype=np.uint8)

    # 4 corners: 0=TL, 1=TR, 2=BR, 3=BL
    positions = [
        (CALIB_MARGIN, CALIB_MARGIN),
        (W - CALIB_MARGIN, CALIB_MARGIN),
        (W - CALIB_MARGIN, H - CALIB_MARGIN),
        (CALIB_MARGIN, H - CALIB_MARGIN),
    ]
    cx_screen, cy_screen = W // 2, H // 2

    # Big arrow from center toward the active corner (only when not in cooldown)
    if 0 <= corner_idx < 4 and cooldown_left <= 0:
        ax, ay = positions[corner_idx]
        _draw_arrow(img, (cx_screen, cy_screen + 80), (ax, ay), (60, 220, 255), thickness=12, tip_size=70)

    # Header / instructions
    cv2.putText(img, "KALIBRATIE", (cx_screen - 150, cy_screen - 130),
                cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255,255,255), 4, cv2.LINE_AA)
    cv2.putText(img, f"Hoek {corner_idx+1} van 4", (cx_screen - 110, cy_screen - 80),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (180,180,180), 2, cv2.LINE_AA)

    if cooldown_left > 0:
        # Show cooldown message instead of capture instructions
        msg1 = "Punt vastgelegd!"
        msg2 = f"Verplaats je hand naar de volgende hoek... {cooldown_left:.1f}s"
        cv2.putText(img, msg1, (cx_screen - 170, cy_screen - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (80, 230, 110), 3, cv2.LINE_AA)
        cv2.putText(img, msg2, (cx_screen - 330, cy_screen + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200,200,200), 2, cv2.LINE_AA)
    else:
        cv2.putText(img, "Plaats je hand op de oplichtende hoek (zie pijl)", (cx_screen - 360, cy_screen - 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200,200,200), 2, cv2.LINE_AA)
        cv2.putText(img, f"Maak een vuist en houd {int(CALIB_HOLD_SECS)} seconden vast", (cx_screen - 260, cy_screen + 0),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200,200,200), 2, cv2.LINE_AA)
    cv2.putText(img, "ESC = annuleren", (cx_screen - 90, cy_screen + 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (140,140,140), 1, cv2.LINE_AA)

    # Draw the 4 corner markers
    for i, (px, py) in enumerate(positions):
        done = i < corner_idx
        active = i == corner_idx and cooldown_left <= 0
        if done:
            color = (80, 230, 110); thick = 4
        elif active:
            # pulse the active corner
            phase = (time.time() * 2.5) % (2 * np.pi)
            pulse = int(8 + 6 * (1 + np.sin(phase)))
            color = (50, 200, 255)
            cv2.circle(img, (px, py), CALIB_RADIUS + pulse, (30, 90, 120), 2)
            thick = 5
        else:
            color = (90, 90, 90); thick = 2
        cv2.circle(img, (px, py), CALIB_RADIUS, color, thick)
        cv2.putText(img, str(i+1), (px-13, py+11),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2, cv2.LINE_AA)
        if active and hold_pct > 0:
            # ring progress around the marker
            cv2.ellipse(img, (px, py), (CALIB_RADIUS+12, CALIB_RADIUS+12),
                        -90, 0, int(360 * hold_pct), (0, 220, 120), 5)

    # BIG countdown number while a fist is held
    if counting and hold_pct > 0 and cooldown_left <= 0:
        secs_left = max(0, int(np.ceil(CALIB_HOLD_SECS * (1 - hold_pct))))
        big = "GO!" if secs_left == 0 else str(secs_left)
        font_scale = 12.0
        thickness = 18
        (tw, th), _ = cv2.getTextSize(big, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        bx = cx_screen - tw // 2
        by = cy_screen + th // 2 + 150
        cv2.putText(img, big, (bx+6, by+6), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (30,30,30), thickness+4, cv2.LINE_AA)
        cv2.putText(img, big, (bx, by),     cv2.FONT_HERSHEY_SIMPLEX, font_scale, (60,220,255), thickness, cv2.LINE_AA)
        bar_w = int(W * hold_pct)
        cv2.rectangle(img, (0, H-12), (bar_w, H), (0, 220, 120), -1)

    # Cooldown progress bar at bottom (green draining to nothing)
    if cooldown_left > 0:
        pct = max(0.0, cooldown_left / CALIB_COOLDOWN_SEC)
        bar_w = int(W * pct)
        cv2.rectangle(img, (0, H-12), (bar_w, H), (40, 180, 230), -1)

    # User's current hand position (rough — pre-homography)
    if hand_screen_pos is not None:
        hx, hy = int(hand_screen_pos[0]), int(hand_screen_pos[1])
        cv2.drawMarker(img, (hx, hy), (255, 80, 80), cv2.MARKER_CROSS, 28, 2)

    cv2.imshow(CALIB_WIN, img)

# ---------- Main loop ------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=None)
    ap.add_argument("--display", type=int, default=None, help="1-based display index (default: beamer if connected)")
    ap.add_argument("--no-preview", action="store_true")
    args = ap.parse_args()

    if not MODEL_PATH.exists():
        print(f"[mp] model file missing: {MODEL_PATH}")
        print(f'  curl -sSL "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task" -o "{MODEL_PATH}"')
        sys.exit(1)

    displays = list_displays()
    print("[disp] connected:")
    for i, d in enumerate(displays):
        print(f"   #{i+1}  id={d['id']}  {d['w']}x{d['h']} @ ({d['x']},{d['y']})  main={d['main']}")
    chosen_idx = (args.display - 1) if args.display else None
    display = pick_display(displays, chosen_idx)
    display_idx = displays.index(display)
    print(f"[disp] controlling: #{display_idx+1}  {display['w']}x{display['h']} @ ({display['x']},{display['y']})")

    samples, grid_cols, grid_rows = load_calibration()
    expected = grid_cols * grid_rows
    if len(samples) != expected or any(s is None for s in samples):
        samples = default_grid_samples(grid_cols, grid_rows)
        print(f"[calib] bootstrapped default {grid_cols}×{grid_rows} grid ({expected} points). DRAG the corners in the preview to match your beamer projection.")
    else:
        print(f"[calib] loaded saved calibration ({grid_cols}×{grid_rows} grid) — drag corners to tweak")
    cells, outer_H = compute_grid_cells(samples, grid_cols, grid_rows)
    calib_present = True
    # Runtime cursor offset (rows); cycle with 'o' key
    cursor_offset_rows = CURSOR_OFFSET_ROWS

    cap = open_camera(args.camera)
    if cap is None:
        print("[cam] FAILED. Check System Settings -> Privacy & Security -> Camera -> enable Terminal, then re-run.")
        sys.exit(1)

    base_options = mp_tasks.BaseOptions(model_asset_path=str(MODEL_PATH))
    options = mp_vision.GestureRecognizerOptions(
        base_options=base_options,
        num_hands=1,
        running_mode=mp_vision.RunningMode.VIDEO,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    recognizer = mp_vision.GestureRecognizer.create_from_options(options)
    print("[mp] gesture recognizer ready")
    print("[run] move hand to point. PINCH (👌) or fist = click. Hand outside calibrated zone = cursor stays put.")

    mirror_x = MIRROR_X_DEFAULT
    smooth_x = display["w"] / 2.0
    smooth_y = display["h"] / 2.0
    fist_down = False
    click_anchor = None     # (x,y) waar een klik viel; cursor blijft hier vast tijdens de klik
    click_is_drag = False   # wordt True zodra je tijdens een klik bewust ver beweegt (= slepen)
    last_move = (None, None)
    fist_history = deque(maxlen=FIST_VOTE_WINDOW)
    fist_consecutive = 0   # count of consecutive frames with fist/pinch detected

    calib_active = False
    calib_corner = 0
    calib_samples = list(samples)
    calib_hold_start = 0.0
    calib_cooldown_until = 0.0   # epoch seconds; no capture/move accepted before this
    start_t = time.monotonic()

    # Pre-create preview window so we can attach a mouse callback for drag-editing corners
    if not args.no_preview:
        cv2.namedWindow(PREVIEW_WIN, cv2.WINDOW_AUTOSIZE)
        mouse_state["samples"] = calib_samples
        cv2.setMouseCallback(PREVIEW_WIN, on_mouse, mouse_state)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.02); continue
            if mirror_x:
                frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts_ms = int((time.monotonic() - start_t) * 1000)
            try:
                result = recognizer.recognize_for_video(mp_image, ts_ms)
            except Exception as e:
                print(f"[mp] recognize error: {e}"); result = None

            landmarks = None
            gesture_name = None
            raw_x = raw_y = 0.0
            screen_pos = None
            in_zone = False

            present = bool(result and result.hand_landmarks)
            if present:
                landmarks = result.hand_landmarks[0]
                if result.gestures and result.gestures[0]:
                    gesture_name = result.gestures[0][0].category_name
                # Stable anchor = avg of wrist + 4 MCP joints. Doesn't drift when
                # fingers curl into a fist.
                raw_x = sum(landmarks[i].x for i in LM_ANCHOR) / len(LM_ANCHOR)
                raw_y = sum(landmarks[i].y for i in LM_ANCHOR) / len(LM_ANCHOR)

                # Map through per-cell homographies (with outer fallback)
                sx_n, sy_n = apply_grid(cells, outer_H, raw_x, raw_y)

                # Cursor offset: lift the cursor N grid-rows ABOVE the hand
                # so the hand doesn't block the visible cursor area.
                offset_y_norm = cursor_offset_rows / max(1, grid_rows - 1)
                cursor_sx_n = sx_n
                cursor_sy_n = sy_n - offset_y_norm

                # "In zone" = the offset cursor lands inside the screen.
                # X must be within the calibrated zone; Y can range as low as
                # (1 + offset) in zone-space so the hand can be below the
                # projection to drive the cursor to the bottom of the screen.
                in_zone = (
                    (-ZONE_MARGIN <= sx_n <= 1 + ZONE_MARGIN)
                    and (-ZONE_MARGIN <= cursor_sy_n <= 1 + ZONE_MARGIN)
                )

                # Compute click triggers FIRST so we can freeze the cursor as
                # soon as the user starts forming a fist (prevents drift off target).
                curled, ratios = fist_score_from_landmarks(landmarks)
                pinch_now, pinch_r = pinch_score(landmarks)
                fist_now = curled >= FIST_FINGERS_NEEDED or gesture_name == "Closed_Fist"
                click_now = pinch_now or fist_now
                fist_history.append(1 if click_now else 0)
                fist_votes = sum(fist_history)
                # Consecutive-frame counter (decoupled from the click vote window).
                # Resets the instant a frame says "no click".
                if click_now:
                    fist_consecutive += 1
                else:
                    fist_consecutive = 0

                # De smoothed cursor-positie volgt ALTIJD de hand. We bevriezen hier
                # niet meer; het bevriezen gebeurt op klik-ankerniveau (zie hieronder)
                # zodat een klik nooit per ongeluk een sleepbeweging wordt.
                if in_zone:
                    sx_clipped = min(max(cursor_sx_n, 0.0), 1.0)
                    sy_clipped = min(max(cursor_sy_n, 0.0), 1.0)
                    sx_local = sx_clipped * display["w"]
                    sy_local = sy_clipped * display["h"]
                    a = SMOOTHING
                    smooth_x = a * smooth_x + (1 - a) * sx_local
                    smooth_y = a * smooth_y + (1 - a) * sy_local
                screen_pos = (smooth_x, smooth_y)
            else:
                curled = 0; ratios = []
                pinch_now = False; pinch_r = 0.0
                fist_history.append(0)
                fist_votes = sum(fist_history)
                fist_consecutive = 0

            # --- Calibration flow ---
            if calib_active:
                # Don't move cursor / don't click while calibrating.
                now_t = time.time()
                in_cooldown = now_t < calib_cooldown_until

                if in_cooldown:
                    # ignore inputs during the cooldown
                    calib_hold_start = 0.0
                elif present and (pinch_now or curled >= FIST_FINGERS_NEEDED or gesture_name == "Closed_Fist"):
                    if calib_hold_start == 0.0:
                        calib_hold_start = now_t
                    held = now_t - calib_hold_start
                    if held >= CALIB_HOLD_SECS:
                        calib_samples[calib_corner] = (raw_x, raw_y)
                        print(f"[calib] corner {calib_corner+1}/4 captured at ({raw_x:.3f},{raw_y:.3f})")
                        calib_hold_start = 0.0
                        calib_corner += 1
                        if calib_corner >= 4:
                            # Legacy 4-pt fist calibration; convert to 2x2 grid.
                            grid_cols = 2; grid_rows = 2
                            cells, outer_H = compute_grid_cells(calib_samples, grid_cols, grid_rows)
                            save_calibration(calib_samples, grid_cols, grid_rows, mirror_x)
                            calib_present = True
                            calib_active = False
                            calib_corner = 0
                            close_calib_overlay()
                            print("[calib] DONE (2x2 grid). Press '+' to densify the grid for curve correction.")
                        else:
                            calib_cooldown_until = now_t + CALIB_COOLDOWN_SEC
                            print(f"[calib] cooldown {CALIB_COOLDOWN_SEC:.0f}s — verplaats je hand naar hoek {calib_corner+1}")
                else:
                    calib_hold_start = 0.0

                if calib_overlay_open[0]:
                    hold_pct = 0.0
                    counting = bool(calib_hold_start)
                    if calib_hold_start:
                        hold_pct = min((time.time() - calib_hold_start) / CALIB_HOLD_SECS, 1.0)
                    cooldown_left = max(0.0, calib_cooldown_until - time.time())
                    cur_screen = None
                    if present:
                        cur_screen = (raw_x * display["w"], raw_y * display["h"])
                    render_calib_overlay(display, calib_corner, hold_pct, cur_screen, counting, cooldown_left)

            # --- Normal use: move cursor + click on fist ---
            elif present and in_zone:
                # 1) Klik-overgangen EERST, zodat we de cursor op het klikpunt
                #    vastzetten op het exacte moment dat de knop omlaag gaat.
                if not fist_down and fist_votes >= FIST_VOTE_DOWN:
                    fist_down = True
                    click_anchor = (smooth_x, smooth_y)   # hier valt de klik -> bevriezen
                    click_is_drag = False
                    agx = display["x"] + click_anchor[0]
                    agy = display["y"] + click_anchor[1]
                    try:
                        pyautogui.moveTo(int(agx), int(agy), _pause=False)
                        last_move = (agx, agy)
                    except Exception as e:
                        print(f"[mouse] moveTo failed: {e}")
                    try:
                        pyautogui.mouseDown(_pause=False)
                        print("[gesture] mouseDown")
                    except Exception as e:
                        print(f"[mouse] mouseDown failed: {e}")
                elif fist_down and fist_votes <= FIST_VOTE_UP:
                    fist_down = False
                    try:
                        pyautogui.mouseUp(_pause=False)
                        print("[gesture] mouseUp")
                    except Exception as e:
                        print(f"[mouse] mouseUp failed: {e}")
                    click_anchor = None
                    click_is_drag = False

                # 2) Cursordoel: tijdens een klik bevroren op het ankerpunt, tenzij je
                #    verder dan DRAG_DEADZONE_PX beweegt (= bewust slepen, bv. kaart pannen).
                if fist_down and click_anchor is not None:
                    if not click_is_drag:
                        ddx = smooth_x - click_anchor[0]
                        ddy = smooth_y - click_anchor[1]
                        if (ddx * ddx + ddy * ddy) ** 0.5 > DRAG_DEADZONE_PX:
                            click_is_drag = True
                    tx, ty = (smooth_x, smooth_y) if click_is_drag else click_anchor
                else:
                    tx, ty = smooth_x, smooth_y

                # 3) Cursor verplaatsen (met de bestaande move-deadzone tegen jitter).
                gx = display["x"] + tx
                gy = display["y"] + ty
                if (last_move[0] is None
                    or abs(gx - last_move[0]) >= MOVE_DEADZONE_PX
                    or abs(gy - last_move[1]) >= MOVE_DEADZONE_PX):
                    try:
                        pyautogui.moveTo(int(gx), int(gy), _pause=False)
                    except Exception as e:
                        print(f"[mouse] moveTo failed: {e}  (check Accessibility permission)")
                    last_move = (gx, gy)
            else:
                # Hand absent OR out of zone: release any held click, do nothing else
                if fist_down:
                    fist_down = False
                    click_anchor = None
                    click_is_drag = False
                    try: pyautogui.mouseUp(_pause=False)
                    except Exception: pass

            if not args.no_preview:
                # Tell the mouse callback the current frame dims so it can hit-test correctly
                mouse_state["frame_w"] = frame.shape[1]
                mouse_state["frame_h"] = frame.shape[0]
                ctx = {
                    "display": display, "display_idx": display_idx,
                    "screen_pos": screen_pos, "fist_down": fist_down,
                    "in_zone": in_zone, "mirror_x": mirror_x,
                    "calib_active": calib_active, "calib_corner": calib_corner,
                    "calib_samples": calib_samples,
                    "calib_present": calib_present,
                    "calib_cooldown_left": max(0.0, calib_cooldown_until - time.time()) if calib_active else 0.0,
                    "mouse_hover": mouse_state["hover"],
                    "mouse_drag":  mouse_state["dragging"],
                    "grid_cols": grid_cols, "grid_rows": grid_rows,
                    "curled": curled if present else None,
                    "ratios": ratios if present else None,
                    "pinch_now": pinch_now if present else None,
                    "pinch_ratio": pinch_r if present else None,
                }
                draw_preview(frame, landmarks, gesture_name, ctx)

                # If user finished a drag, recompute cells + save
                if mouse_state["needs_save"]:
                    mouse_state["needs_save"] = False
                    if all(s is not None for s in calib_samples):
                        cells, outer_H = compute_grid_cells(calib_samples, grid_cols, grid_rows)
                        save_calibration(calib_samples, grid_cols, grid_rows, mirror_x)
                        calib_present = True
                        print("[calib] grid moved -> cells recomputed and saved")
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('c'):
                    print("[info] fist-based calibration is disabled in grid mode — use mouse drag, '+'/'-' for grid size, 'r' to reset, 'a' for auto-calibration")
                elif key == ord('a'):
                    print("[auto-calib] starting — step out of the camera view!")
                    if fist_down:
                        try: pyautogui.mouseUp(_pause=False)
                        except Exception: pass
                        fist_down = False
                    if grid_cols > AUTO_CAL_MAX_GRID or grid_rows > AUTO_CAL_MAX_GRID:
                        print(f"[auto-calib] grid was {grid_cols}×{grid_rows} — capping at {AUTO_CAL_MAX_GRID}×{AUTO_CAL_MAX_GRID} for reliability (press '+' afterwards to densify manually)")
                    new_samples, new_cols, new_rows = auto_calibrate(cap, display, mirror_x, grid_cols, grid_rows)
                    if new_samples is not None and len(new_samples) == new_cols * new_rows:
                        grid_cols, grid_rows = new_cols, new_rows
                        calib_samples[:] = new_samples
                        mouse_state["samples"] = calib_samples
                        cells, outer_H = compute_grid_cells(calib_samples, grid_cols, grid_rows)
                        save_calibration(calib_samples, grid_cols, grid_rows, mirror_x)
                        calib_present = True
                        print(f"[auto-calib] DONE — {grid_cols}×{grid_rows} grid calibrated automatically")
                    else:
                        print("[auto-calib] failed — kept previous calibration. Try: darker room, camera aimed at full projection, no glare.")
                elif key == ord('r'):
                    # Reset to default regular grid (drag-edit from there)
                    new_samples = default_grid_samples(grid_cols, grid_rows)
                    calib_samples[:] = new_samples
                    mouse_state["samples"] = calib_samples
                    cells, outer_H = compute_grid_cells(calib_samples, grid_cols, grid_rows)
                    save_calibration(calib_samples, grid_cols, grid_rows, mirror_x)
                    print(f"[calib] reset to default {grid_cols}×{grid_rows} grid — drag points to fit your projection")
                elif key in (ord('+'), ord('=')):
                    if grid_cols < GRID_MAX_DIM and grid_rows < GRID_MAX_DIM:
                        grid_cols += 1; grid_rows += 1
                        new_samples = default_grid_samples(grid_cols, grid_rows)
                        calib_samples[:] = new_samples
                        mouse_state["samples"] = calib_samples
                        cells, outer_H = compute_grid_cells(calib_samples, grid_cols, grid_rows)
                        save_calibration(calib_samples, grid_cols, grid_rows, mirror_x)
                        print(f"[calib] grid increased to {grid_cols}×{grid_rows} = {len(calib_samples)} points")
                elif key in (ord('-'), ord('_')):
                    if grid_cols > GRID_MIN_DIM and grid_rows > GRID_MIN_DIM:
                        grid_cols -= 1; grid_rows -= 1
                        new_samples = default_grid_samples(grid_cols, grid_rows)
                        calib_samples[:] = new_samples
                        mouse_state["samples"] = calib_samples
                        cells, outer_H = compute_grid_cells(calib_samples, grid_cols, grid_rows)
                        save_calibration(calib_samples, grid_cols, grid_rows, mirror_x)
                        print(f"[calib] grid decreased to {grid_cols}×{grid_rows} = {len(calib_samples)} points")
                elif key == 27:  # esc
                    if calib_active:
                        calib_active = False
                        calib_corner = 0
                        calib_hold_start = 0.0
                        close_calib_overlay()
                        print("[calib] cancelled")
                elif key == ord('m'):
                    mirror_x = not mirror_x
                    print(f"[cfg] mirror_x={mirror_x}")
                elif key == ord('d'):
                    display_idx = (display_idx + 1) % len(displays)
                    display = displays[display_idx]
                    if calib_active:
                        # re-open overlay on new display
                        close_calib_overlay()
                        open_calib_overlay(display)
                    print(f"[disp] controlling: #{display_idx+1}  {display['w']}x{display['h']}")
                elif key == ord('o'):
                    # Cycle cursor offset: 0 → 1 → 2 → 3 → 0
                    cursor_offset_rows = (int(cursor_offset_rows) + 1) % 4
                    print(f"[cfg] cursor_offset_rows={cursor_offset_rows} (cursor sits {cursor_offset_rows} grid-rows above hand)")
    except KeyboardInterrupt:
        pass
    finally:
        if fist_down:
            try: pyautogui.mouseUp(_pause=False)
            except Exception: pass
        close_calib_overlay()
        cap.release()
        if not args.no_preview:
            cv2.destroyAllWindows()
        recognizer.close()
        print("bye")

if __name__ == "__main__":
    main()
