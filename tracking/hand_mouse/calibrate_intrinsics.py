#!/usr/bin/env python3
"""
calibrate_intrinsics.py — Fase 1 van het 3D-brein: lens-kalibratie per camera.

Meet de camera-matrix K + lens-distortie van één camera met een checkerboard.
Corrigeert o.a. de gebogen DJI-lens, zodat rechte wereld-lijnen ook recht in het
beeld worden. Onmisbaar vóór 3D-triangulatie.

TWEE MODELLEN:
  --model standard  (default) → pinhole + radiaal. Goed voor de iPhone (al vrij
                                rechtlijnig).
  --model fisheye               → OpenCV fisheye-model. NODIG voor de DJI Action
                                (ultra-wide); het standaardmodel ballonneert daar.

Voorbereiding:
  1. Print checkerboard_9x6.png (10×7 vakjes = 9×6 BINNENhoeken).
  2. Plak hem PLAT op een stijve plaat. Mag niet bollen.
  3. Meet één vakje (mm) → geef mee via --square-mm (alleen voor latere metrische
     3D-stappen; voor K/distortie maakt de maat niet uit).

DE GOUDEN REGEL: vul met het bord het HELE beeld, vooral de HOEKEN, en houd hem
schuin onder veel verschillende hoeken. De dekkings-overlay (groen) toont waar al
data is — werk tot het beeld redelijk vol groen is. ~15-25 gevarieerde views.

Gebruik:
    # DJI (top, meestal idx 0) — fisheye!
    python calibrate_intrinsics.py --idx 0 --name dji --model fisheye --square-mm 25
    # iPhone (side, meestal idx 2) — standaard
    python calibrate_intrinsics.py --idx 2 --name iphone --model standard --square-mm 25

Bediening:
    SPATIE = view vastleggen (alleen bij GROEN herkend bord)
    u      = laatste view ongedaan maken
    c      = nu kalibreren (min. 8 views)
    ESC    = stoppen zonder opslaan

Output: camera_intrinsics.json (key per --name; bevat 'model', 'K', 'dist', ...).
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

log = logging.getLogger("calibrate_intrinsics")
HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "camera_intrinsics.json"
MIN_VIEWS = 8


def _calibrate_standard(objpoints, imgpoints, img_size, flags=0):
    rms, K, dist, _r, _t = cv2.calibrateCamera(
        objpoints, imgpoints, img_size, None, None, flags=flags)
    return float(rms), K, dist.ravel()


def _calibrate_fisheye(objpoints, imgpoints, img_size):
    obj = [o.reshape(1, -1, 3).astype(np.float64) for o in objpoints]
    img = [c.reshape(1, -1, 2).astype(np.float64) for c in imgpoints]
    K = np.zeros((3, 3))
    D = np.zeros((4, 1))
    rvecs = [np.zeros((1, 1, 3), dtype=np.float64) for _ in obj]
    tvecs = [np.zeros((1, 1, 3), dtype=np.float64) for _ in obj]
    flags = (cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC + cv2.fisheye.CALIB_FIX_SKEW)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-6)
    rms, K, D, _r, _t = cv2.fisheye.calibrate(obj, img, img_size, K, D, rvecs, tvecs, flags, crit)
    return float(rms), K, D.ravel()


def main() -> int:
    p = argparse.ArgumentParser(description="Lens-intrinsics kalibratie (Fase 1 van het 3D-brein).")
    p.add_argument("--idx", type=int, required=True, help="OpenCV camera-index.")
    p.add_argument("--name", required=True, help="Sleutel in de JSON, bv. 'dji' of 'iphone'.")
    p.add_argument("--model", choices=("standard", "fisheye"), default="standard",
                   help="'fisheye' voor de DJI (ultra-wide), 'standard' voor de iPhone.")
    p.add_argument("--cols", type=int, default=9, help="Binnenhoeken horizontaal (default 9).")
    p.add_argument("--rows", type=int, default=6, help="Binnenhoeken verticaal (default 6).")
    p.add_argument("--square-mm", type=float, default=25.0, help="Vakjesgrootte in mm (default 25).")
    p.add_argument("--shots", type=int, default=20, help="Auto-kalibreren bij dit aantal views.")
    p.add_argument("--balance", type=float, default=0.3,
                   help="Undistort-preview: 0=strak bijsnijden, 1=alles behouden (default 0.3).")
    p.add_argument("--no-fix-k3", action="store_true",
                   help="Standaardmodel: laat de k3-radiaalterm vrij. Default = k3 vastzetten "
                        "(stabieler bij al-rechtlijnige camera's zoals de iPhone).")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cap = cv2.VideoCapture(args.idx, cv2.CAP_AVFOUNDATION)
    if not cap.isOpened():
        log.error("Kan camera-index %d niet openen. Check eerst dual_cam_test.py.", args.idx)
        return 1
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    pattern = (args.cols, args.rows)
    objp = np.zeros((args.rows * args.cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:args.cols, 0:args.rows].T.reshape(-1, 2)
    objp *= args.square_mm

    objpoints: list[np.ndarray] = []
    imgpoints: list[np.ndarray] = []
    img_size: tuple[int, int] | None = None
    coverage: np.ndarray | None = None  # persistente dekkings-overlay

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    find_flags = (cv2.CALIB_CB_ADAPTIVE_THRESH
                  + cv2.CALIB_CB_NORMALIZE_IMAGE
                  + cv2.CALIB_CB_FAST_CHECK)

    win = f"intrinsics — {args.name} [{args.model}] (idx {args.idx})"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    log.info("Model: %s. Vul het HELE beeld incl. hoeken; bord schuin; ~%d views.",
             args.model, args.shots)
    log.info("SPATIE=vastleggen (bij groen), u=undo, c=kalibreren, ESC=stop.")

    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.01)
            continue
        if coverage is None:
            coverage = np.zeros(frame.shape[:2], np.uint8)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        img_size = (gray.shape[1], gray.shape[0])
        found, corners = cv2.findChessboardCorners(gray, pattern, find_flags)
        disp = frame.copy()
        # Dekkings-overlay: groen waar al views zijn vastgelegd.
        green = np.zeros_like(disp)
        green[:, :, 1] = coverage
        disp = cv2.addWeighted(disp, 1.0, green, 0.5, 0)
        if found:
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            cv2.drawChessboardCorners(disp, pattern, corners, found)

        col = (0, 220, 0) if found else (0, 0, 255)
        cv2.putText(disp,
                    f"views: {len(objpoints)}/{args.shots}   "
                    f"{'BORD OK — SPATIE' if found else 'geen bord in beeld'}",
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2, cv2.LINE_AA)
        cv2.putText(disp, "vul vooral de HOEKEN groen | SPATIE=leg vast  u=undo  c=kalibreren  ESC=stop",
                    (20, disp.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (230, 230, 230), 1, cv2.LINE_AA)
        cv2.imshow(win, disp)

        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            log.info("Gestopt zonder opslaan.")
            cap.release()
            cv2.destroyAllWindows()
            return 1
        if key == ord(" ") and found:
            objpoints.append(objp.copy())
            imgpoints.append(corners)
            # Teken het bedekte gebied in de coverage-overlay (convex hull v/d hoeken).
            hull = cv2.convexHull(corners.astype(np.int32))
            cv2.fillConvexPoly(coverage, hull, 255)
            log.info("view %d vastgelegd", len(objpoints))
        elif key == ord("u") and objpoints:
            objpoints.pop()
            imgpoints.pop()
            log.info("laatste view verwijderd (%d over) — overlay blijft staan", len(objpoints))
        elif (key == ord("c") or len(objpoints) >= args.shots) and len(objpoints) >= MIN_VIEWS:
            break
        elif key == ord("c") and len(objpoints) < MIN_VIEWS:
            log.info("Nog te weinig views (%d/%d) om te kalibreren.", len(objpoints), MIN_VIEWS)

    cv2.destroyAllWindows()
    cap.release()

    if len(objpoints) < MIN_VIEWS or img_size is None:
        log.error("Te weinig views (%d). Minimaal %d nodig.", len(objpoints), MIN_VIEWS)
        return 1

    log.info("Kalibreren (%s) met %d views…", args.model, len(objpoints))
    try:
        if args.model == "fisheye":
            rms, K, dist = _calibrate_fisheye(objpoints, imgpoints, img_size)
        else:
            std_flags = 0 if args.no_fix_k3 else cv2.CALIB_FIX_K3
            rms, K, dist = _calibrate_standard(objpoints, imgpoints, img_size, std_flags)
    except cv2.error as e:
        log.error("Kalibratie faalde: %s", e)
        log.error("Vaak = te eenvormige/slechte views. Probeer opnieuw met meer variatie + hoeken.")
        return 1

    log.info("RMS reprojectie-fout: %.3f px  (goed = < ~0.8; >1.5 = views opnieuw)", rms)
    log.info("K =\n%s", np.array2string(K, precision=2, suppress_small=True))
    log.info("dist = %s", np.array2string(dist, precision=4, suppress_small=True))
    # ——— Automatische sanity-checks ————————————————————————————————————————
    fx, fy = float(K[0, 0]), float(K[1, 1])
    ratio = fx / fy if fy else 0.0
    sane = True
    if rms > 1.0:
        sane = False
        log.warning("⚠️  RMS %.2f > 1.0 = onbetrouwbaar. Meer/gevarieerdere views: kantel "
                    "(~30-45°), roteer, dichtbij/veraf, vul de HOEKEN; bord groot, scherp én STIL.", rms)
    if not (0.85 <= ratio <= 1.18):
        sane = False
        log.warning("⚠️  fx/fy = %.2f (hoort ~1.0). Beeld is waarschijnlijk anamorf gerekt — "
                    "kalibreer op de native resolutie, bv. --width 1920 --height 1080.", ratio)
    if sane:
        log.info("✅ Sanity-check ok: RMS laag én fx≈fy (ratio %.2f).", ratio)

    data: dict = {}
    if args.out.exists():
        try:
            data = json.loads(args.out.read_text())
        except Exception:
            data = {}
    data[args.name] = {
        "model": args.model,
        "K": K.tolist(),
        "dist": [float(v) for v in dist],
        "image_size": [int(img_size[0]), int(img_size[1])],
        "rms": float(rms),
        "board": {"cols": args.cols, "rows": args.rows, "square_mm": args.square_mm},
        "n_views": len(objpoints),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    args.out.write_text(json.dumps(data, indent=2))
    log.info("✓ Opgeslagen onder key '%s' (model=%s) in %s", args.name, args.model, args.out)

    # ——— Visuele check: undistorted vs origineel ————————————————————————————
    log.info("Undistort-preview: links=origineel, rechts=gecorrigeerd. ESC = sluiten.")
    log.info("GOED = rechte randen worden recht en het beeld blijft 'normaal'. "
             "Een ballon/koepel = nog mis → meer hoek-dekking nodig.")
    cap2 = cv2.VideoCapture(args.idx, cv2.CAP_AVFOUNDATION)
    cap2.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap2.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    win2 = f"undistort-check — {args.name}  (ESC=sluiten)"
    cv2.namedWindow(win2, cv2.WINDOW_NORMAL)

    map1 = map2 = None
    if args.model == "fisheye":
        D = np.array(dist, dtype=np.float64).reshape(4, 1)
        new_k = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(
            K, D, img_size, np.eye(3), balance=args.balance)
        map1, map2 = cv2.fisheye.initUndistortRectifyMap(
            K, D, np.eye(3), new_k, img_size, cv2.CV_16SC2)
    else:
        D = np.array(dist, dtype=np.float64).reshape(-1, 1)
        new_k, _roi = cv2.getOptimalNewCameraMatrix(K, D, img_size, args.balance, img_size)

    while cap2.isOpened():
        ok, frame = cap2.read()
        if not ok:
            time.sleep(0.01)
            continue
        if map1 is not None:
            und = cv2.remap(frame, map1, map2, cv2.INTER_LINEAR)
        else:
            und = cv2.undistort(frame, K, D, None, new_k)
        cv2.putText(frame, "origineel", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2, cv2.LINE_AA)
        cv2.putText(und, f"undistorted [{args.model}]", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 220, 0), 2, cv2.LINE_AA)
        cv2.imshow(win2, np.hstack([frame, und]))
        if (cv2.waitKey(1) & 0xFF) == 27:
            break
    cap2.release()
    cv2.destroyAllWindows()
    log.info("Volgende: doe dit ook voor de andere camera, dan door naar Fase 2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
