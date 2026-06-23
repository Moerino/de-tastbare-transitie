#!/usr/bin/env python3
"""
run_install.py — één-commando pipeline voor de HyperBRIDGE-installatie.

Voert in volgorde uit:
  1. Camera-verificatie  → alleen DJI (side) + iPhone Desk View (top)
  2. Kalibratie          → 9×9 dot-projectie op beamer + tafel-meting side
  3. Tracker             → twee preview-vensters + WebSocket-bridge naar HTML

Voorbeeld:
  ../dji_tracker/.venv/bin/python run_install.py --top-idx 3 --side-idx 0

Opties om stappen over te slaan:
  --skip-verify    Sla camera-check over
  --skip-calib     Gebruik bestaande calibration_dual.json (geen nieuwe meting)
  --display-idx 1  Projecteer kalibratie op tweede scherm (beamer)
  --cols 3 --rows 3   Snellere maar minder precieze kalibratie (9 i.p.v. 81 dots)

Druk in elk venster 'q' om door te gaan naar de volgende stap.
Druk Ctrl+C in de terminal om de hele pipeline af te breken.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON = HERE.parent / "dji_tracker" / ".venv" / "bin" / "python"


def auto_pick_beamer_display() -> int | None:
    """Kies automatisch het beamer-scherm.

    Logica: als er meer dan één scherm is, gebruik dan het eerste niet-main
    scherm (= de beamer). Als er maar één is, return None → kalibratie valt
    terug op het hoofdscherm.
    """
    try:
        import hand_mouse as hm
        displays = hm.list_displays()
        if len(displays) <= 1:
            return None
        for i, d in enumerate(displays):
            if not d.get("main"):
                return i
        return 1  # fallback: tweede in de lijst
    except Exception as exc:
        print(f"[warn] kan schermen niet detecteren: {exc}")
        return None


def step(num: int, total: int, title: str) -> None:
    bar = "─" * 70
    print(f"\n{bar}\n[{num}/{total}] {title}\n{bar}")


def run(cmd: list[str]) -> int:
    print(f">>> {' '.join(shlex.quote(c) for c in cmd)}\n")
    return subprocess.call(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Single-command installatie-pipeline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--top-idx", type=int, default=3,
                        help="OpenCV index van top-cam (iPhone Desk View via OBS).")
    parser.add_argument("--side-idx", type=int, default=0,
                        help="OpenCV index van side-cam (DJI Action 5 Pro).")
    parser.add_argument("--display-idx", type=int, default=None,
                        help="Scherm waarop kalibratie-dots worden geprojecteerd. "
                             "Default: auto-detect (beamer / tweede scherm).")
    parser.add_argument("--cols", type=int, default=9)
    parser.add_argument("--rows", type=int, default=9)
    parser.add_argument("--mirror-x", action="store_true")
    parser.add_argument("--skip-verify", action="store_true",
                        help="Sla camera-verificatie over.")
    parser.add_argument("--skip-calib", action="store_true",
                        help="Sla kalibratie over (gebruik bestaande JSON).")
    args = parser.parse_args()

    if not PYTHON.exists():
        print(f"[ERR] venv-python niet gevonden op {PYTHON}")
        return 1

    total = 3 - int(args.skip_verify) - int(args.skip_calib)
    n = 0

    # ─── 1. Camera-verificatie ───────────────────────────────────────────
    if not args.skip_verify:
        n += 1
        step(n, total, "CAMERA-VERIFICATIE")
        print("Twee vensters worden geopend: top-cam (Desk View) en side-cam (DJI).")
        print("Controleer of de juiste beelden tonen. Druk 'q' om door te gaan.\n")
        cmd = [
            str(PYTHON), str(HERE / "dual_cam_test.py"),
            "--indices", f"{args.top_idx},{args.side_idx}",
            "--labels", "top-desk-view,side-dji",
        ]
        rc = run(cmd)
        if rc != 0:
            print("[!] Camera-verificatie afgebroken.")
            return rc

    # ─── 2. Kalibratie ───────────────────────────────────────────────────
    calib_path = HERE / "calibration_dual.json"
    if not args.skip_calib:
        n += 1
        step(n, total, "KALIBRATIE OP BEAMER")

        # Auto-detect het beamer-scherm als de gebruiker geen --display-idx
        # heeft meegegeven. Zonder beamer aangesloten valt het terug op het
        # hoofdscherm met een waarschuwing.
        display_idx = args.display_idx
        if display_idx is None:
            display_idx = auto_pick_beamer_display()
            if display_idx is not None:
                print(f"[disp] auto-detect: projecteer op scherm #{display_idx + 1} (beamer).")
            else:
                print("[!] Geen tweede scherm gevonden — kalibratie valt op hoofd-scherm.")
                print("    Sluit eerst de beamer aan en herstart, of forceer met --display-idx N.")

        print("Stap A: 9×9 dot-projectie op het beamer-scherm.")
        print("Stap B: leg wijsvinger plat op tafel, daarna 1 cm omhoog.\n")
        cmd = [
            str(PYTHON), str(HERE / "calibrate_dual.py"),
            "--top-idx", str(args.top_idx),
            "--side-idx", str(args.side_idx),
            "--cols", str(args.cols),
            "--rows", str(args.rows),
            "--out", str(calib_path),
        ]
        if display_idx is not None:
            cmd += ["--display-idx", str(display_idx)]
        if args.mirror_x:
            cmd += ["--mirror-x"]
        rc = run(cmd)
        if rc != 0:
            print("[!] Kalibratie mislukt.")
            return rc
    else:
        if not calib_path.exists():
            print(f"[!] --skip-calib gebruikt maar geen bestaande {calib_path.name} gevonden.")
            return 1

    # ─── 3. Tracker starten ──────────────────────────────────────────────
    n += 1
    step(n, total, "TRACKER GESTART (multi-touch + WebSocket-bridge)")
    print("Twee preview-vensters: top + side.")
    print("De WebSocket-bridge luistert op ws://localhost:8765 voor de browser.")
    print("Open http://localhost:8008/map-app.html en zie de ghost-cursors.")
    print("Druk 'q' in een venster om te stoppen.\n")
    cmd = [
        str(PYTHON), str(HERE / "dual_cam_tracker.py"),
        "--top-idx", str(args.top_idx),
        "--side-idx", str(args.side_idx),
        "--calib", str(calib_path),
        "--debug",
    ]
    return run(cmd)


if __name__ == "__main__":
    sys.exit(main())
