#!/usr/bin/env python3
"""
tune_calibration.py — zoek automatisch de juiste auto-cal-parameters.

Wat het doet (~60 sec, geen interactie nodig):
  1. Opent top-cam (iPhone Desk View via OBS) + side-cam (DJI)
  2. Opent fullscreen overlay op het beamer-scherm
  3. Doorloopt 10 verschillende parameter-combinaties:
       - dot-grootte: 33 → 80 → 150 → 200 px
       - dot-kleur: wit / geel / magenta / cyaan / rood / zwart-op-wit
       - threshold: 5 / 10 / 15 / 25 / 40
       - exposure-tijd: kort / lang
  4. Per combinatie:
       a. Projecteert zwart (baseline)        → capture beide cams
       b. Projecteert dot in midden            → capture beide cams
       c. Berekent diff, zoekt blob in beide
       d. Logt resultaat (gedetecteerd ja/nee, area, max diff)
  5. Print samenvatting + aanbevolen params
  6. Schrijft `tuning_results.json` met alle metingen

Top-cam (iPhone) heeft prioriteit; side-cam wordt als bonus gemeten.

Gebruik:
  cd "/.../tracking/hand_mouse" && \
    ../dji_tracker/.venv/bin/python tune_calibration.py \
       --top-idx 3 --side-idx 0 --display-idx 1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import hand_mouse as hm  # voor list_displays / pick_display

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "tuning_results.json"

# 10 test-combinaties — van eenvoudig naar agressief naar inverted.
# Velden:
#   radius:        dot-straal in beamer-pixels
#   color:         BGR — kleur van de dot (of bg bij invert=True)
#   threshold:     min brightness-diff (0..255) om als dot te tellen
#   min_blob:      min contour-area in cam-pixels
#   settle_frames: aantal frames droppen na display-update (drain buffer)
#   grace_s:       waittijd voor capture (sec)
#   invert:        False = witte dot op zwart; True = zwarte dot op wit
TESTS = [
    # Baseline — wat calibrate_dual.py nu gebruikt
    dict(name="01-default-wit",    radius=33,  color=(255, 255, 255), threshold=25,
         min_blob=20,  settle_frames=18, grace_s=0.9, invert=False),
    # Stap 1: dot vergroten (vaak het hele probleem op iPhone Desk View)
    dict(name="02-grote-wit",      radius=80,  color=(255, 255, 255), threshold=25,
         min_blob=40,  settle_frames=18, grace_s=0.9, invert=False),
    # Stap 2: nog groter + lagere threshold (vangen van zachte randen)
    dict(name="03-huge-wit-soft",  radius=150, color=(255, 255, 255), threshold=10,
         min_blob=80,  settle_frames=18, grace_s=0.9, invert=False),
    # Stap 3: kleurkanaal forceren — Desk View kan witte highlights afvlakken
    dict(name="04-magenta-mid",    radius=100, color=(255,   0, 255), threshold=15,
         min_blob=60,  settle_frames=18, grace_s=0.9, invert=False),
    dict(name="05-cyaan-mid",      radius=100, color=(255, 255,   0), threshold=15,
         min_blob=60,  settle_frames=18, grace_s=0.9, invert=False),
    dict(name="06-geel-mid",       radius=100, color=(  0, 255, 255), threshold=15,
         min_blob=60,  settle_frames=18, grace_s=0.9, invert=False),
    dict(name="07-rood-mid",       radius=100, color=(  0,   0, 255), threshold=15,
         min_blob=60,  settle_frames=18, grace_s=0.9, invert=False),
    # Stap 4: super-lage threshold + langere exposure (vangt vrijwel alles)
    dict(name="08-soft-traag",     radius=100, color=(255, 255, 255), threshold=5,
         min_blob=60,  settle_frames=36, grace_s=2.0, invert=False),
    # Stap 5: extreem groot, lage threshold (laatste redmiddel voor witte dots)
    dict(name="09-max-wit-soft",   radius=250, color=(255, 255, 255), threshold=5,
         min_blob=100, settle_frames=36, grace_s=2.0, invert=False),
    # Stap 6: inverted (zwarte dot op witte achtergrond) — soms beter voor
    # camera's die hooglichten clippen; meet brightness-drop i.p.v. -stijging
    dict(name="10-inverted-zwart", radius=120, color=(  0,   0,   0), threshold=15,
         min_blob=60,  settle_frames=18, grace_s=0.9, invert=False),
]


# ——— Helpers ————————————————————————————————————————————————————————————
def open_cam(idx: int, label: str) -> cv2.VideoCapture | None:
    cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)
    if not cap.isOpened():
        print(f"[!] kan {label}-cam index {idx} niet openen — sla over")
        cap.release()
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    # Warmup
    for _ in range(8):
        cap.grab()
    return cap


def open_overlay(display: dict) -> str:
    win = "tune-calib"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.moveWindow(win, display["x"], display["y"])
    cv2.resizeWindow(win, display["w"], display["h"])
    try:
        cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    except Exception:
        pass
    return win


def render_bg(display: dict, invert: bool = False) -> np.ndarray:
    bg = 255 if invert else 0
    return np.full((display["h"], display["w"], 3), bg, dtype=np.uint8)


def render_dot(display: dict, color: tuple[int, int, int], radius: int,
               x_frac: float, y_frac: float, invert: bool = False) -> np.ndarray:
    img = render_bg(display, invert=invert)
    cx = int(x_frac * display["w"])
    cy = int(y_frac * display["h"])
    cv2.circle(img, (cx, cy), radius, color, -1, cv2.LINE_AA)
    return img


def capture_after_grace(cap: cv2.VideoCapture, settle_frames: int, grace_s: float) -> np.ndarray | None:
    """Wacht grace_s, drain `settle_frames` frames, grab een verse frame."""
    cv2.waitKey(int(grace_s * 1000))
    for _ in range(settle_frames):
        cap.grab()
    ok, frame = cap.read()
    return frame if ok else None


def detect_blob(diff_gray: np.ndarray, threshold: int, min_blob: int) -> dict | None:
    """Vind de grootste blob in de drempelafbeelding. Returns dict of None."""
    _, mask = cv2.threshold(diff_gray, threshold, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best: dict | None = None
    best_area = 0.0
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < min_blob:
            continue
        M = cv2.moments(cnt)
        if M["m00"] == 0:
            continue
        cx = M["m10"] / M["m00"]
        cy = M["m01"] / M["m00"]
        if area > best_area:
            best_area = area
            best = {"x": round(cx, 1), "y": round(cy, 1), "area": round(area, 1)}
    return best


def analyze_pair(baseline: np.ndarray | None, dot: np.ndarray | None,
                 threshold: int, min_blob: int) -> dict:
    """Vergelijk twee frames, retour: detected/max_diff/blob-info."""
    if baseline is None or dot is None:
        return {"detected": False, "reason": "geen frame"}
    diff = cv2.absdiff(dot, baseline)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (9, 9), 0)
    max_diff = int(gray.max())
    mean_diff = float(gray.mean())
    blob = detect_blob(gray, threshold, min_blob)
    if blob is None:
        # Diagnose
        reason = "geen blob > threshold"
        if max_diff < threshold:
            reason = f"max_diff={max_diff} < threshold={threshold}"
        return {"detected": False, "reason": reason,
                "max_diff": max_diff, "mean_diff": round(mean_diff, 2)}
    blob["detected"] = True
    blob["max_diff"] = max_diff
    blob["mean_diff"] = round(mean_diff, 2)
    return blob


# ——— Main loop ————————————————————————————————————————————————————————
def run_all(top_cap, side_cap, display, args) -> list[dict]:
    win = open_overlay(display)
    results: list[dict] = []
    n = len(TESTS)
    for i, test in enumerate(TESTS, start=1):
        print(f"\n[{i}/{n}] {test['name']}  "
              f"r={test['radius']} c={test['color']} thr={test['threshold']} "
              f"min_blob={test['min_blob']} inv={test['invert']}")

        # Stap A — toon achtergrond, capture baseline.
        cv2.imshow(win, render_bg(display, invert=test["invert"]))
        cv2.waitKey(150)
        top_baseline = capture_after_grace(top_cap, test["settle_frames"], test["grace_s"])
        side_baseline = None
        if side_cap is not None:
            side_baseline = capture_after_grace(side_cap, 8, 0.1)

        # Stap B — toon dot in midden, capture beide.
        cv2.imshow(win, render_dot(display, test["color"], test["radius"], 0.5, 0.5,
                                   invert=test["invert"]))
        cv2.waitKey(150)
        top_dot = capture_after_grace(top_cap, test["settle_frames"], test["grace_s"])
        side_dot = None
        if side_cap is not None:
            side_dot = capture_after_grace(side_cap, 8, 0.1)

        # Stap C — analyseer
        top_res = analyze_pair(top_baseline, top_dot, test["threshold"], test["min_blob"])
        side_res = ({} if side_cap is None
                    else analyze_pair(side_baseline, side_dot, test["threshold"], test["min_blob"]))

        results.append({"test": test, "top": top_res, "side": side_res})

        # Korte log-regel per cam
        def fmt(label, res):
            if not res:
                return f"{label}: (geen cam)"
            if res.get("detected"):
                return (f"{label}: ✅ blob area={res['area']} "
                        f"@({res['x']:.0f},{res['y']:.0f}) max_diff={res['max_diff']}")
            return f"{label}: ❌ {res.get('reason', '?')} max_diff={res.get('max_diff', '?')}"
        print(f"     {fmt('TOP ', top_res)}")
        print(f"     {fmt('SIDE', side_res)}")

    cv2.destroyWindow(win)
    return results


def summarize(results: list[dict]) -> dict:
    """Pick best test per cam: detected + area between 80 and 30000."""
    def score(res: dict) -> float:
        if not res.get("detected"):
            return -1
        area = res.get("area", 0)
        # Penalize blobs die te klein of belachelijk groot zijn.
        if area < 80:
            return area * 0.5
        if area > 30000:
            return 1000 - (area / 1000)
        # Anders: hoe groter (binnen rede) hoe betrouwbaarder; plus brightness diff.
        return min(area, 3000) + 5 * res.get("max_diff", 0)

    top_scored = [(score(r["top"]), r) for r in results]
    side_scored = [(score(r["side"]), r) for r in results if r["side"]]

    top_best = max(top_scored, key=lambda x: x[0])
    side_best = max(side_scored, key=lambda x: x[0]) if side_scored else (None, None)

    out: dict = {"top_best": None, "side_best": None}
    if top_best[0] > 0:
        out["top_best"] = {"name": top_best[1]["test"]["name"],
                           "params": top_best[1]["test"], "result": top_best[1]["top"]}
    if side_best[0] is not None and side_best[0] > 0:
        out["side_best"] = {"name": side_best[1]["test"]["name"],
                            "params": side_best[1]["test"], "result": side_best[1]["side"]}
    return out


def print_summary(results: list[dict], best: dict) -> None:
    bar = "=" * 78
    print(f"\n{bar}\nSAMENVATTING\n{bar}")
    print(f"{'TEST':<22}{'TOP':<10}{'TOP-area':<12}{'SIDE':<10}{'SIDE-area':<12}")
    print("-" * 78)
    for r in results:
        n = r["test"]["name"]
        t = r["top"]
        s = r["side"] or {}
        t_mark = "✅" if t.get("detected") else "❌"
        s_mark = "✅" if s.get("detected") else ("—" if not s else "❌")
        print(f"{n:<22}{t_mark:<10}{str(t.get('area', '-')):<12}{s_mark:<10}{str(s.get('area', '-')):<12}")
    print(bar)
    if best["top_best"]:
        b = best["top_best"]
        print(f"🏆 BESTE voor iPhone Desk View: {b['name']}")
        print(f"   params: radius={b['params']['radius']}  color={b['params']['color']}  "
              f"threshold={b['params']['threshold']}  min_blob={b['params']['min_blob']}  "
              f"settle={b['params']['settle_frames']}  grace={b['params']['grace_s']}  "
              f"invert={b['params']['invert']}")
    else:
        print("⚠️  GEEN ENKELE test slaagde voor iPhone Desk View.")
        print("    Mogelijke oorzaken:")
        print("    • OpenCV-venster landt op verkeerd scherm (zie hand_mouse.py opmerking)")
        print("    • iPhone Desk View staat niet op de beamer-projectie gericht")
        print("    • Omgevingslicht te fel — dim de kamer en probeer opnieuw")
    if best["side_best"]:
        b = best["side_best"]
        print(f"🏆 BESTE voor DJI side-cam:   {b['name']}")
        print(f"   params: radius={b['params']['radius']}  color={b['params']['color']}  "
              f"threshold={b['params']['threshold']}  min_blob={b['params']['min_blob']}")
    else:
        print("(side-cam: geen succesvolle detectie — verwacht, zie tafel-meting in Fase B)")
    print(bar)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auto-tune van auto_calibrate parameters voor iPhone Desk View + DJI.",
    )
    parser.add_argument("--top-idx", type=int, default=3)
    parser.add_argument("--side-idx", type=int, default=0)
    parser.add_argument("--display-idx", type=int, default=None,
                        help="Scherm voor projectie. Default: auto-pick eerste niet-main.")
    parser.add_argument("--countdown", type=int, default=5,
                        help="Seconden voor de tests beginnen (tijd om weg te stappen).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    # Display kiezen
    displays = hm.list_displays()
    if not displays:
        print("[!] geen schermen gedetecteerd")
        return 1
    display_idx = args.display_idx
    if display_idx is None:
        # Pak het eerste niet-main scherm (= beamer)
        for i, d in enumerate(displays):
            if not d.get("main"):
                display_idx = i
                break
    display = hm.pick_display(displays, display_idx)
    print(f"[disp] projectie op scherm #{display_idx if display_idx is not None else 0}: "
          f"{display['w']}x{display['h']} @ ({display['x']},{display['y']}) main={display.get('main')}")

    # Cams openen
    top_cap = open_cam(args.top_idx, "top")
    if top_cap is None:
        print("[!] top-cam (iPhone Desk View) niet beschikbaar — afbreken")
        return 1
    side_cap = open_cam(args.side_idx, "side")
    if side_cap is None:
        print("[!] side-cam (DJI) niet beschikbaar — test gaat alleen voor top-cam door")

    # Countdown
    print(f"\nTest start over {args.countdown} sec — stap uit het beeld van beide cams!")
    for sec in range(args.countdown, 0, -1):
        print(f"  {sec}...")
        time.sleep(1)

    # Run
    try:
        results = run_all(top_cap, side_cap, display, args)
        best = summarize(results)
        print_summary(results, best)
        args.out.write_text(json.dumps({"results": results, "best": best}, indent=2, default=str))
        print(f"\n💾 Volledige meetdata opgeslagen in: {args.out}")
    finally:
        top_cap.release()
        if side_cap is not None:
            side_cap.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
