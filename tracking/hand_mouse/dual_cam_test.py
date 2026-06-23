"""
Dual-camera test voor de HyperBRIDGE-installatie.

Doel: bevestigen dat OpenCV/AVFoundation op deze Mac twee externe camera's
tegelijk kan openen voordat we de echte tracker bouwen.

Het script:
  1. Probeert camera-indices 0 t/m 5 te openen (extra hoog vanwege Desk View).
  2. Toont elk werkend feed in een eigen venster met de index in de titelbalk.
  3. Drukt voor elk werkend feed resolutie en FPS af in de terminal.
  4. Drukt de door macOS gerapporteerde camera-namen + Unique IDs af zodat de
     gebruiker visueel kan matchen welk indexnummer welke camera is.

Bediening:
  - Druk in een willekeurig venster op 'q' om te stoppen.
  - Of Ctrl+C in de terminal.

Verwacht op deze Mac (3 jun, na Desk View activeren):
  - index 0 = FaceTime HD
  - index 1 = OsmoAction5pro
  - index 2 = Moerino 17 Camera (iPhone gewoon)
  - index 3 = Moerino 17 Camera (Desk View)  ← als macOS hem als aparte
                                                AVFoundation-device exposeert

Noteer welke index welke camera laat zien — dat hebben we later nodig voor
`dual_cam_tracker.py --top-idx N --side-idx M`.
"""

import argparse
import json
import subprocess
import sys
import time

import cv2

MAX_INDEX_TO_TRY = 6  # extra ruimte voor iPhone Desk View als 4e/5e device
DESIRED_W = 1280
DESIRED_H = 720


def list_macos_cameras() -> list[dict]:
    """Vraag macOS via `system_profiler` naar alle bekende camera-devices.

    Geeft een lijst dicts terug met 'name', 'model_id' en 'unique_id'.
    De volgorde komt niet 1-op-1 overeen met OpenCV-indices, maar wel
    consistent met wat AVFoundation rapporteert. Match visueel via het
    preview-venster.
    """
    try:
        result = subprocess.run(
            ["system_profiler", "SPCameraDataType", "-json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        data = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
        return []

    entries = data.get("SPCameraDataType", [])
    cams: list[dict] = []
    for e in entries:
        # Elk entry: { "_name": "OsmoAction5pro", "spcamera_model-id": "...", "spcamera_unique-id": "..." }
        cams.append({
            "name": e.get("_name", "(naamloos)"),
            "model_id": e.get("spcamera_model-id", ""),
            "unique_id": e.get("spcamera_unique-id", ""),
        })
    return cams


def open_camera(index: int):
    """Probeer camera op `index` te openen. Geeft VideoCapture terug of None."""
    # cv2.CAP_AVFOUNDATION dwingt de native macOS-backend af; voorkomt fall-back
    # naar trage of buggy alternatieven.
    cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    if not cap.isOpened():
        cap.release()
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, DESIRED_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, DESIRED_H)
    # Eerste frame ophalen om te bevestigen dat de feed echt werkt — sommige
    # AVFoundation-devices openen succesvol maar leveren nooit een frame.
    ok, _ = cap.read()
    if not ok:
        cap.release()
        return None
    return cap


def describe(cap) -> str:
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    return f"{w}x{h} @ {fps:.1f} fps"


def main() -> int:
    parser = argparse.ArgumentParser(description="Toon één of meer camera-feeds.")
    parser.add_argument("--indices", type=str, default=None,
                        help="Komma-gescheiden lijst van OpenCV-indices om te tonen "
                             "(bv. --indices 3,0). Default: probeer alles 0..5.")
    parser.add_argument("--labels", type=str, default=None,
                        help="Komma-gescheiden labels voor de indices "
                             "(bv. --labels top,side). Optioneel.")
    args = parser.parse_args()

    only = None
    labels = {}
    if args.indices:
        only = [int(x.strip()) for x in args.indices.split(",") if x.strip()]
        if args.labels:
            label_parts = [x.strip() for x in args.labels.split(",")]
            for i, lbl in zip(only, label_parts):
                labels[i] = lbl

    # ——— Eerst: macOS-camera-inventaris ———————————————————————————————————
    cams = list_macos_cameras()
    if cams:
        print("\nmacOS rapporteert deze camera-devices:")
        print("-" * 78)
        for i, c in enumerate(cams):
            print(f"  {i+1}. {c['name']}")
            if c.get('model_id'):
                print(f"     model: {c['model_id']}")
            if c.get('unique_id'):
                print(f"     unique-id: {c['unique_id']}")
        print("-" * 78)
        print("Let op: de macOS-volgorde komt vaak (niet altijd) overeen met de")
        print("OpenCV-index. Match visueel via het preview-venster.\n")
    else:
        print("\n⚠️  Kon system_profiler niet aanroepen — alleen indices, geen namen.\n")

    # ——— OpenCV-indices proberen —————————————————————————————————————————
    indices_to_try = only if only is not None else list(range(MAX_INDEX_TO_TRY))
    print(f"Probeer OpenCV camera-indices: {indices_to_try}")
    open_caps = {}
    for idx in indices_to_try:
        cap = open_camera(idx)
        if cap is not None:
            open_caps[idx] = cap
            lbl = labels.get(idx, "")
            tag = f"  [{lbl}]" if lbl else ""
            print(f"  ✅ index {idx}{tag}: open — {describe(cap)}")
        else:
            print(f"  ❌ index {idx}: niet beschikbaar")

    if not open_caps:
        print("\nGeen enkele camera kon worden geopend. Check kabels + permissies.")
        return 1

    print(
        f"\n{len(open_caps)} camera(s) gelijktijdig open. Druk 'q' in een venster om te stoppen.\n"
        "Vergelijk de beelden met de naam-lijst hierboven om de juiste indices te kiezen.\n"
    )

    last_log = time.monotonic()
    frame_counts = {idx: 0 for idx in open_caps}

    try:
        while True:
            for idx, cap in open_caps.items():
                ok, frame = cap.read()
                if not ok:
                    continue
                frame_counts[idx] += 1
                # Index groot in beeld zodat je direct weet welk venster welke is.
                lbl = labels.get(idx, "")
                overlay_text = f"index {idx}" + (f"  ({lbl})" if lbl else "")
                cv2.putText(
                    frame,
                    overlay_text,
                    (24, 56),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.4,
                    (0, 255, 0),
                    3,
                    cv2.LINE_AA,
                )
                # Als er een camera met deze positie in de macOS-lijst staat,
                # toon die naam onder de index als hint (best-effort match
                # op volgorde — geen garantie).
                if cams and idx < len(cams) + 1 and idx > 0:
                    hint = cams[min(idx - 1, len(cams) - 1)]["name"]
                    cv2.putText(
                        frame,
                        f"hint: {hint}",
                        (24, 92),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        (200, 255, 200),
                        2,
                        cv2.LINE_AA,
                    )
                lbl = labels.get(idx, "")
                win_title = f"Camera {lbl} (idx {idx})" if lbl else f"Camera index {idx}"
                cv2.imshow(win_title, frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):  # 'q' of ESC
                break

            # Elke 2 seconden een live FPS-rapportje in de terminal.
            now = time.monotonic()
            if now - last_log >= 2.0:
                elapsed = now - last_log
                summary = ", ".join(
                    f"idx {i}: {frame_counts[i] / elapsed:.1f} fps"
                    for i in frame_counts
                )
                print(summary)
                frame_counts = {i: 0 for i in open_caps}
                last_log = now
    except KeyboardInterrupt:
        pass
    finally:
        for cap in open_caps.values():
            cap.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
