#!/usr/bin/env python3
"""
dual_cam_tracker.py — twee-cam multi-touch tracker voor de HyperBRIDGE-installatie.

Pipeline per frame:
  top-cam (iPhone, boven plateau)  --> MediaPipe HandLandmarker
    -> per finger: pixel (x,y) -> homography -> screen pixel
  side-cam (DJI Action 5 Pro, zijkant) --> MediaPipe HandLandmarker
    -> per finger: pixel-y wordt vergeleken met `table_y_pixel`
       (touching = fingertip is dichtbij tafel-lijn in side-view)
  fusie -> touch_state.TouchStateTracker -> WS-events via ws_bridge

Gebruik (zonder kalibratie, alleen preview):
    python dual_cam_tracker.py --top-idx 2 --side-idx 1 --debug

Met kalibratie (productie):
    python dual_cam_tracker.py --calib calibration_dual.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

import hand_mouse as hm  # hergebruik grid-mapping + homografie-helpers
import pyautogui
from touch_state import TouchStateTracker
from ws_bridge import WSBridge

# pyautogui mag niet failen bij hoek-aanrakingen of langzame bewegingen
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

log = logging.getLogger("dual_cam_tracker")

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = HERE / "hand_landmarker.task"
DEFAULT_CALIB = HERE / "calibration_dual.json"

# MediaPipe fingertip landmark indices
FINGER_TIPS = {
    "thumb": 4,
    "index": 8,
    "middle": 12,
    "ring": 16,
    "pinky": 20,
}
LM_WRIST = 0
LM_INDEX_MCP = 5
LM_PINKY_MCP = 17


# ——— Kalibratie ————————————————————————————————————————————————————————
@dataclass
class Calibration:
    """Grid-kalibratie + tafel-meting voor de dual-cam tracker.

    samples: lijst van (x, y) genormaliseerd op cam-frame (0..1) — geschreven door
             auto_calibrate uit hand_mouse.py.
    cells:   per-cel homography zodat lokale distortie wordt gecorrigeerd.
    outer_H: fallback homography voor punten buiten het grid (extrapoleren).
    """
    samples: list[tuple[float, float]]
    cols: int
    rows: int
    mirror_x: bool
    cells: list                            # uit hm.compute_grid_cells
    outer_H: np.ndarray                    # 3x3 fallback
    table_y_pixel: int | None              # side-cam: pixel-Y van het tafeloppervlak
    touch_threshold_px: int                # side-cam: hoever boven de lijn telt nog als touching
    screen_w: int
    screen_h: int
    # Offset van het kalibratie-scherm in macOS global display space. Voor de
    # main display is dit (0,0); voor een tweede scherm (beamer) bv. (1800,0).
    # Nodig om pyautogui.moveTo de juiste fysieke positie te geven.
    screen_x: int = 0
    screen_y: int = 0
    # ——— Side-cam twee-laag touch-systeem ——————————————————————————————————
    # BOTTOM layer: het beamer-vlak op tafelhoogte. Inside = vinger raakt aan.
    # TOP    layer: ~1 cm boven het beamer-vlak. Bovenkant = ceiling.
    #
    # Touch-detectie:
    #   - Inside bottom polygon → touching
    #   - Boven top polygon (Y < min Y van top polygon) → te hoog, geen touch
    #
    # `side_zone` is een backward-compat veld dat we alleen lezen als
    # _bottom/_top niet bestaan in de JSON.
    side_zone_bottom: list[tuple[int, int]] | None = None
    side_zone_top: list[tuple[int, int]] | None = None
    side_zone: list[tuple[int, int]] | None = None  # legacy fallback
    # Corrigerende cam→scherm homografie uit fine_tune_calibration.py.
    # Als gezet, gebruikt de tracker DEZE in plaats van de optische 9×9 grid.
    # Lost axis-swap problemen op die de optische cal soms heeft.
    finger_homography: np.ndarray | None = None
    # Per-vinger homografieën uit calibrate_all_fingers.py.
    # Sleutel = "L-thumb", "R-index", etc. Heeft VOORRANG boven finger_homography
    # zodat elke vinger zijn eigen offset correct krijgt — verhelpt het residu
    # waarbij verschillende vingers door MediaPipe iets verschillend worden
    # geplaatst in de DJI-cam, ook als de globale mapping al perfect is.
    finger_homographies: dict[str, np.ndarray] | None = None
    # Per-vinger fusie-homografieën uit calibrate_all_fingers.py (nieuwe versie):
    #   _top  = DJI → scherm  (levert de X-as)
    #   _side = iPhone → scherm (levert de Y-as)
    # In --fusion modus krijgt elke vinger zo zijn eigen X (DJI) én Y (iPhone).
    finger_homographies_top: dict[str, np.ndarray] | None = None
    finger_homographies_side: dict[str, np.ndarray] | None = None
    # ——— Sensor-fusie: iPhone side-cam → scherm-mapping ————————————————————
    # Homografie die de iPhone-fingertip-pixel naar scherm-pixel mapt. Gebruikt
    # in --fusion modus: de DJI kijkt schuin en is langs zijn diepte-as (near-far
    # op tafel) onnauwkeurig; de iPhone kijkt daar juist dwars op en meet die as
    # precies. We nemen dan screen-X van de iPhone en screen-Y van de DJI.
    # Geschreven door calibrate_side_screen.py.
    side_homography: np.ndarray | None = None
    # ——— Per-vinger OFFSET-verfijning (calibrate_all_fingers.py, nieuwe aanpak) ——
    # Kleine additieve correctie (dx, dy) in scherm-pixels per vinger-ID. Sleutel
    # = "L-thumb" / "R-index" etc. Wordt NA de 9×9-basis opgeteld; corrigeert het
    # residu dat MediaPipe per vinger iets anders plaatst. Anders dan de oude
    # per-vinger homografieën kan een offset NOOIT de hele positie verdraaien —
    # het is puur een verschuiving, geen herprojectie.
    finger_offsets: dict[str, tuple[float, float]] | None = None

    @classmethod
    def load(cls, path: Path) -> "Calibration":
        if not path.exists():
            log.warning("Geen kalibratie-bestand op %s — preview-only mode.", path)
            return cls([], 0, 0, False, [], np.eye(3), None, 20, 1920, 1080, 0, 0,
                       None, None, None, None, None, None)
        data = json.loads(path.read_text())
        samples = [tuple(s) for s in data.get("samples", [])]
        cols = int(data.get("cols", 0))
        rows = int(data.get("rows", 0))
        cells: list = []
        outer_H = np.eye(3, dtype=np.float64)
        if samples and cols >= 2 and rows >= 2:
            cells, outer_H = hm.compute_grid_cells(samples, cols, rows)

        def _parse_poly(raw) -> list[tuple[int, int]] | None:
            if not isinstance(raw, list) or len(raw) < 3:
                return None
            try:
                return [(int(p[0]), int(p[1])) for p in raw]
            except (TypeError, ValueError, IndexError):
                return None

        bottom = _parse_poly(data.get("side_zone_bottom"))
        top = _parse_poly(data.get("side_zone_top"))
        legacy = _parse_poly(data.get("side_zone"))

        # Optionele fine-tune homografie uit fine_tune_calibration.py
        fh = None
        raw_fh = data.get("finger_homography")
        if isinstance(raw_fh, list) and len(raw_fh) == 3:
            try:
                fh = np.array(raw_fh, dtype=np.float64)
                if fh.shape != (3, 3):
                    fh = None
            except (TypeError, ValueError):
                fh = None

        # Optionele per-vinger homografieën uit calibrate_all_fingers.py
        def _parse_h_dict(raw):
            if not isinstance(raw, dict):
                return None
            parsed: dict[str, np.ndarray] = {}
            for k, v in raw.items():
                if isinstance(v, list) and len(v) == 3:
                    try:
                        m = np.array(v, dtype=np.float64)
                        if m.shape == (3, 3):
                            parsed[k] = m
                    except (TypeError, ValueError):
                        pass
            return parsed or None

        fhs = _parse_h_dict(data.get("finger_homographies"))
        fhs_top = _parse_h_dict(data.get("finger_homographies_top"))
        fhs_side = _parse_h_dict(data.get("finger_homographies_side"))
        # Optionele iPhone side-cam → scherm homografie (sensor-fusie)
        sh = None
        raw_sh = data.get("side_homography")
        if isinstance(raw_sh, list) and len(raw_sh) == 3:
            try:
                sh = np.array(raw_sh, dtype=np.float64)
                if sh.shape != (3, 3):
                    sh = None
            except (TypeError, ValueError):
                sh = None

        # Optionele per-vinger offsets (dx, dy) uit calibrate_all_fingers.py
        def _parse_offsets(raw):
            if not isinstance(raw, dict):
                return None
            parsed: dict[str, tuple[float, float]] = {}
            for k, v in raw.items():
                if isinstance(v, (list, tuple)) and len(v) == 2:
                    try:
                        parsed[k] = (float(v[0]), float(v[1]))
                    except (TypeError, ValueError):
                        pass
            return parsed or None

        finger_offsets = _parse_offsets(data.get("finger_offsets"))

        # Backward compat: oude calibration_dual.json had alleen `side_zone`.
        # Behandel die als bottom; genereer top automatisch 20 px erboven.
        if bottom is None and legacy is not None:
            bottom = legacy
            if top is None:
                top = [(x, max(0, y - 20)) for (x, y) in legacy]
        return cls(
            samples=samples,
            cols=cols,
            rows=rows,
            mirror_x=bool(data.get("mirror_x", False)),
            cells=cells,
            outer_H=outer_H,
            table_y_pixel=data.get("table_y_pixel"),
            touch_threshold_px=int(data.get("touch_threshold_px", 20)),
            screen_w=int(data.get("screen_w", 1920)),
            screen_h=int(data.get("screen_h", 1080)),
            screen_x=int(data.get("screen_x", 0)),
            screen_y=int(data.get("screen_y", 0)),
            side_zone_bottom=bottom,
            side_zone_top=top,
            side_zone=legacy,
            finger_homography=fh,
            finger_homographies=fhs,
            finger_homographies_top=fhs_top,
            finger_homographies_side=fhs_side,
            side_homography=sh,
            finger_offsets=finger_offsets,
        )

    @property
    def has_grid(self) -> bool:
        return bool(self.cells)


# ——— Camera-worker ——————————————————————————————————————————————————————
@dataclass
class HandObservation:
    """Eén gedetecteerde hand uit één camera-frame."""
    handedness: str                # "Left" / "Right" zoals MediaPipe het meldt
    landmarks_px: list[tuple[float, float]]   # 21 punten, pixel-coords in dit cam-frame
    palm_facing: bool              # True als handpalm naar camera wijst
    timestamp_ms: int


class CameraWorker(threading.Thread):
    """Leest één camera, draait MediaPipe HandLandmarker, publiceert laatste detecties.

    Loopt in eigen thread zodat top en side parallel verwerken zonder seriële
    latency-stapeling.
    """

    def __init__(self, idx: int, role: str, model_path: Path, max_hands: int = 4,
                 min_confidence: float = 0.3,
                 width: int = 1280, height: int = 720, fps: int = 30):
        super().__init__(name=f"cam-{role}", daemon=True)
        self.idx = idx
        self.role = role
        self.max_hands = max_hands
        self._min_conf = float(min_confidence)
        self._cap_w = int(width)
        self._cap_h = int(height)
        self._cap_fps = int(fps)
        self._model_path = model_path
        self._cap: cv2.VideoCapture | None = None
        self._landmarker: mp_vision.HandLandmarker | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # Laatste verwerkte frame + observaties (voor main thread én preview).
        self._latest_frame: np.ndarray | None = None
        self._latest_obs: list[HandObservation] = []
        self._frame_w = 0
        self._frame_h = 0
        self._frames_processed = 0
        self._start_t = time.monotonic()
        # Monotonic ms-timestamp voor MediaPipe VIDEO-modus.
        self._mp_ts = 0

    def _setup(self) -> bool:
        self._cap = cv2.VideoCapture(self.idx, cv2.CAP_AVFOUNDATION)
        if not self._cap.isOpened():
            log.error("[%s] kan camera %d niet openen", self.role, self.idx)
            return False
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._cap_w)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._cap_h)
        # Vraag hogere fps aan. AVFoundation honoreert dit alleen als de
        # camera het ondersteunt bij deze resolutie — lagere resolutie =
        # meer kans op 60fps. We lezen de werkelijke waarde terug ter controle.
        self._cap.set(cv2.CAP_PROP_FPS, self._cap_fps)
        ok, frame = self._cap.read()
        if not ok:
            log.error("[%s] geen frame van camera %d", self.role, self.idx)
            return False
        self._frame_h, self._frame_w = frame.shape[:2]
        actual_fps = self._cap.get(cv2.CAP_PROP_FPS) or 0.0
        log.info("[%s] camera %d ok: %dx%d  aangevraagd %dfps → camera meldt %.0ffps",
                 self.role, self.idx, self._frame_w, self._frame_h,
                 self._cap_fps, actual_fps)

        base_options = mp_tasks.BaseOptions(model_asset_path=str(self._model_path))
        options = mp_vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=self.max_hands,
            running_mode=mp_vision.RunningMode.VIDEO,
            min_hand_detection_confidence=self._min_conf,
            min_hand_presence_confidence=self._min_conf,
            min_tracking_confidence=self._min_conf,
        )
        self._landmarker = mp_vision.HandLandmarker.create_from_options(options)
        return True

    def run(self) -> None:
        if not self._setup():
            self._stop.set()
            return
        try:
            while not self._stop.is_set():
                ok, frame = self._cap.read()  # type: ignore[union-attr]
                if not ok:
                    time.sleep(0.01)
                    continue
                self._process_frame(frame)
        finally:
            if self._cap is not None:
                self._cap.release()
            if self._landmarker is not None:
                self._landmarker.close()

    def _process_frame(self, frame_bgr: np.ndarray) -> None:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        # MediaPipe VIDEO mode eist strikt monotoon stijgende ms-timestamps.
        self._mp_ts += 1
        result = self._landmarker.detect_for_video(mp_image, self._mp_ts)  # type: ignore[union-attr]

        obs: list[HandObservation] = []
        if result and result.hand_landmarks:
            for i, landmarks in enumerate(result.hand_landmarks):
                handedness = "Right"
                if result.handedness and i < len(result.handedness):
                    cat = result.handedness[i][0]
                    handedness = cat.category_name
                pts = [(lm.x * self._frame_w, lm.y * self._frame_h) for lm in landmarks]
                palm_facing = self._is_palm_facing(landmarks)
                obs.append(HandObservation(
                    handedness=handedness,
                    landmarks_px=pts,
                    palm_facing=palm_facing,
                    timestamp_ms=self._mp_ts,
                ))

        with self._lock:
            self._latest_frame = frame_bgr
            self._latest_obs = obs
            self._frames_processed += 1

    @staticmethod
    def _is_palm_facing(landmarks) -> bool:
        """Schat of de handpalm naar de camera wijst via een normaalvector.

        Kruisproduct van (wrist→indexMCP) en (wrist→pinkyMCP). De Z-component
        in MediaPipe's genormaliseerde wereldcoördinaten geeft palm-of-rug.
        Negatief = palm naar camera (in MediaPipe's conventie voor RH-coords).
        """
        try:
            w = landmarks[LM_WRIST]
            i = landmarks[LM_INDEX_MCP]
            p = landmarks[LM_PINKY_MCP]
            v1 = (i.x - w.x, i.y - w.y, i.z - w.z)
            v2 = (p.x - w.x, p.y - w.y, p.z - w.z)
            # Cross product Z-component
            cz = v1[0] * v2[1] - v1[1] * v2[0]
            return cz > 0  # convention check; finetune per cam
        except Exception:
            return True

    def snapshot(self) -> tuple[np.ndarray | None, list[HandObservation], int, int]:
        with self._lock:
            frame = None if self._latest_frame is None else self._latest_frame.copy()
            return frame, list(self._latest_obs), self._frame_w, self._frame_h

    def fps(self) -> float:
        elapsed = max(0.01, time.monotonic() - self._start_t)
        return self._frames_processed / elapsed

    def stop(self) -> None:
        self._stop.set()


# ——— Fusie ——————————————————————————————————————————————————————————————
def map_screen(point_cam: tuple[float, float], calib: "Calibration",
               cam_w: int, cam_h: int,
               hand_label: str | None = None,
               finger_name: str | None = None,
               use_offsets: bool = True) -> tuple[float, float]:
    """Map een cam-pixel naar een scherm-pixel.

    Voorkeursvolgorde:
      1. Optische 9×9 grid (uit Fase A van calibrate_dual.py) = ROBUUSTE BASIS.
         Indien aanwezig wordt hier de per-vinger OFFSET (calibrate_all_fingers.py)
         bovenop opgeteld als kleine additieve correctie (zie hieronder).
      2. Globale finger_homography (uit fine_tune_calibration.py) — single
         cam→scherm mapping op basis van index-finger metingen.
      3. Lineaire fallback zonder kalibratie.
    """
    x, y = point_cam

    # ——— BASIS-mapping: 9×9 grid (robuust, dichtste kalibratie) ———————————
    # We gebruiken het 9×9 grid als BASIS. De per-vinger kalibratie wordt
    # daarna als kleine OFFSET-correctie (dx, dy) toegepast, NIET als volledige
    # vervanging. Een offset kan nooit "de verkeerde kant op" sturen — dat
    # verhelpt de regressie waarbij per-vinger homografieën de positie
    # compleet verdraaiden.
    if calib.has_grid:
        nx = x / cam_w
        ny = y / cam_h
        if calib.mirror_x:
            nx = 1.0 - nx
        sx_n, sy_n = hm.apply_grid(calib.cells, calib.outer_H, nx, ny)
        sx = sx_n * calib.screen_w
        sy = sy_n * calib.screen_h
        # Per-vinger offset-verfijning: + (dx, dy) voor deze specifieke vinger.
        if use_offsets and calib.finger_offsets and hand_label and finger_name:
            off = calib.finger_offsets.get(f"{hand_label}-{finger_name}")
            if off is not None:
                sx += off[0]
                sy += off[1]
        return sx, sy

    # ——— Fallback: globale single-finger homografie (oude werkende basis) ——
    if calib.finger_homography is not None:
        pt = np.array([[[float(x), float(y)]]], dtype=np.float64)
        out = cv2.perspectiveTransform(pt, calib.finger_homography)
        return float(out[0, 0, 0]), float(out[0, 0, 1])

    # ——— Lineaire fallback —————————————————————————————————————————————————
    return x / cam_w * calib.screen_w, y / cam_h * calib.screen_h


def is_touching_side(
    fingertip_x: float,
    fingertip_y: float,
    table_y: int | None,
    threshold: int,
    side_zone_bottom: list[tuple[int, int]] | None = None,
    side_zone_top: list[tuple[int, int]] | None = None,
    _zone_cache: dict | None = None,
) -> bool:
    """Side-cam touch-test met twee-laag systeem.

    Twee polygonen vormen samen een 3D-band in de side-view:
      - **bottom layer** = beamer-oppervlak. Vinger binnen deze polygon = AAN.
      - **top layer** = ~1 cm boven het oppervlak. Vinger boven deze polygon
        (lager Y in image) wordt afgewezen — voorkomt valse touches van
        zwaaiende handen hoger boven de tafel.

    Touch is geldig als:
      1. (optioneel) bottom polygon: vinger zit erin → aanraking
      2. (optioneel) top polygon: vinger zit NIET boven de top-rand
      3. fallback voor oude kalibraties: vinger Y >= table_y - threshold
    """
    # Cache de numpy-arrays. cv2.pointPolygonTest eist np.ndarray, opnieuw
    # bouwen per fingertip × frame is verspilling.
    if _zone_cache is None:
        _zone_cache = {}

    def poly_arr(key, raw):
        if raw is None:
            return None
        cached = _zone_cache.get(key)
        if cached is None:
            cached = np.array(raw, dtype=np.int32)
            _zone_cache[key] = cached
        return cached

    bottom_arr = poly_arr("bottom", side_zone_bottom)
    top_arr = poly_arr("top", side_zone_top)

    # Bottom polygon: vinger MOET hier in zitten om aanraking te zijn.
    if bottom_arr is not None:
        inside = cv2.pointPolygonTest(
            bottom_arr, (float(fingertip_x), float(fingertip_y)), False
        )
        if inside < 0:
            return False

    # Top polygon: vinger mag NIET boven de bovenkant zitten (te hoog in lucht).
    # min Y van de polygon = bovenste rand in image (Y groeit naar beneden).
    if top_arr is not None:
        min_top_y = int(top_arr[:, 1].min())
        if fingertip_y < min_top_y:
            return False

    # Als geen polygon → fallback op de oude table_y + threshold logica.
    if bottom_arr is None:
        if table_y is None:
            return False
        return fingertip_y >= (table_y - threshold)

    # Met bottom polygon: alleen-binnen-zone telt al als touching.
    return True


# ——— Hoofdloop ——————————————————————————————————————————————————————————
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-idx", type=int, default=2,
                        help="OpenCV index van de top-camera (iPhone). Default 2.")
    parser.add_argument("--side-idx", type=int, default=1,
                        help="OpenCV index van de side-camera (DJI). Default 1.")
    parser.add_argument("--calib", type=Path, default=DEFAULT_CALIB,
                        help="Pad naar calibration_dual.json")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL,
                        help="Pad naar hand_landmarker.task")
    parser.add_argument("--debug", action="store_true",
                        help="Toon preview-vensters met landmarks.")
    parser.add_argument("--no-ws", action="store_true",
                        help="Geen WebSocket-server starten (pure preview).")
    parser.add_argument("--no-cursor", action="store_true",
                        help="Stuur de systeem-muiscursor NIET aan (alleen WS).")
    parser.add_argument("--primary-hand", choices=("R", "L", "auto"), default="auto",
                        help="Welke hand drijft de systeem-cursor aan. 'auto' = rechts "
                             "indien aanwezig, anders eerste gedetecteerde hand.")
    parser.add_argument("--screen-x", type=int, default=None,
                        help="Override van screen_x offset uit calibration_dual.json. "
                             "Gebruik dit als de muis op het verkeerde scherm landt.")
    parser.add_argument("--screen-y", type=int, default=None,
                        help="Override van screen_y offset uit calibration_dual.json.")
    parser.add_argument("--min-confidence", type=float, default=0.3,
                        help="MediaPipe hand-detection drempel (0..1). Lager = vangt "
                             "kleinere/vagere handen zoals een hand ver van de DJI.")
    parser.add_argument("--fusion", action="store_true",
                        help="Sensor-fusie: neem screen-X van de iPhone (precies langs "
                             "de DJI-diepte-as) en screen-Y van de DJI. Vereist "
                             "side_homography in de kalibratie (calibrate_side_screen.py).")
    parser.add_argument("--fingers", choices=("index", "all"), default="all",
                        help="Welke vingertoppen tracken. 'all' = duim+wijs+midden+ring+"
                             "pink (default — nodig voor multi-touch + pinch-zoom). "
                             "'index' = alleen wijsvinger (single-cursor mode).")
    parser.add_argument("--no-finger-offsets", action="store_true",
                        help="Schakel de per-vinger offset-verfijning uit "
                             "(finger_offsets uit calibrate_all_fingers.py). Toont de "
                             "kale 9×9-basis — handig om te vergelijken.")
    parser.add_argument("--smoothing-cutoff", type=float, default=0.4,
                        help="One Euro Filter mincutoff (default 0.4). Lager = stiller "
                             "bij stilstaande hand. 1.0 = oude default.")
    parser.add_argument("--smoothing-beta", type=float, default=0.10,
                        help="One Euro Filter beta (default 0.10). Hoger = sneller "
                             "reageren bij snelle beweging. 0.05 = oude default.")
    parser.add_argument("--top-width", type=int, default=960,
                        help="DJI capture-breedte. Lager = sneller MediaPipe = hogere FPS.")
    parser.add_argument("--top-height", type=int, default=540)
    parser.add_argument("--top-fps", type=int, default=60,
                        help="Aangevraagde DJI fps. Camera honoreert alleen wat hij kan.")
    # iPhone side-cam: TERUG op 1280x720. De 640x480 verlaging gaf geen fps-winst
    # (MediaPipe is de bottleneck, niet de camera) maar wél slechtere
    # vinger-detectie. Hogere resolutie = nauwkeuriger touch-detectie.
    parser.add_argument("--side-width", type=int, default=1280)
    parser.add_argument("--side-height", type=int, default=720)
    parser.add_argument("--side-fps", type=int, default=60,
                        help="Aangevraagde iPhone fps. Camera honoreert wat hij kan.")
    parser.add_argument("--smoothing", type=float, default=0.5,
                        help="Cursor-smoothing 0..1. 1=geen lag, jittery; "
                             "0.3=soepel maar lichte lag. Default 0.5 = balans.")
    args = parser.parse_args()

    # Vroege stdout-output zodat je meteen weet dat het script start. MediaPipe
    # kan 5-15 sec silent zijn tijdens model-load; zonder dit lijkt het of de
    # terminal hangt.
    print(f"[start] dual_cam_tracker — top-idx={args.top_idx} side-idx={args.side_idx}",
          flush=True)
    print("[start] Laden van MediaPipe model + openen camera's "
          "(kan 5-15 sec duren)...", flush=True)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s",
                        force=True)

    if not args.model.exists():
        log.error("Model niet gevonden: %s", args.model)
        return 1

    calib = Calibration.load(args.calib)
    # CLI override van scherm-offset (gebruik als muis op verkeerd scherm landt).
    if args.screen_x is not None:
        calib.screen_x = args.screen_x
    if args.screen_y is not None:
        calib.screen_y = args.screen_y
    log.info("Kalibratie: grid=%s  table_y=%s  thresh=%dpx",
             f"{calib.cols}×{calib.rows} ({len(calib.samples)} samples)"
                if calib.has_grid else "✗ (lineair fallback)",
             calib.table_y_pixel, calib.touch_threshold_px)
    log.info("Cursor-offset (scherm 2 = beamer): X=%d Y=%d  scherm-grootte=%dx%d",
             calib.screen_x, calib.screen_y, calib.screen_w, calib.screen_h)
    if calib.has_grid:
        log.info("BASIS = 9×9 grid (%d samples).", len(calib.samples))
        if calib.finger_offsets and not args.no_finger_offsets:
            log.info("➕ Per-vinger offset-verfijning ACTIEF (%d vingers): %s",
                     len(calib.finger_offsets),
                     ", ".join(sorted(calib.finger_offsets.keys())))
        elif calib.finger_offsets and args.no_finger_offsets:
            log.info("Per-vinger offset-verfijning UIT (--no-finger-offsets) — kale basis.")
        else:
            log.info("Geen finger_offsets in kalibratie — draai calibrate_all_fingers.py "
                     "voor de offset-verfijning.")
    elif calib.finger_homography is not None:
        log.info("Globale fine-tune homografie actief (single mapping voor alle vingers).")
    else:
        log.info("Geen finger-cal aanwezig — optische 9×9 grid wordt gebruikt.")

    # Sensor-fusie status
    if args.fusion:
        per_finger_side = bool(calib.finger_homographies_side)
        if per_finger_side:
            log.info("🔀 FUSIE AAN: screen-X van DJI + screen-Y van iPhone "
                     "(per-vinger, %d vingers).", len(calib.finger_homographies_side))
        elif calib.side_homography is not None:
            log.info("🔀 FUSIE AAN: screen-X van DJI + screen-Y van iPhone (globaal).")
        else:
            log.warning("⚠️  --fusion gevraagd maar GEEN iPhone-mapping in kalibratie. "
                        "Draai calibrate_all_fingers.py (nieuw) of calibrate_side_screen.py. "
                        "Val terug op DJI-only.")

    bridge: WSBridge | None = None
    if not args.no_ws:
        bridge = WSBridge()
        bridge.start()

    state = TouchStateTracker(
        smoothing_cutoff=args.smoothing_cutoff,
        smoothing_beta=args.smoothing_beta,
    )
    # Gedeelde cache voor cv2.pointPolygonTest — voorkomt np.array() per frame
    # per fingertip (5 vingers × 4 handen × 30 fps = 600 allocations/sec).
    zone_cache: dict = {}

    # Welke vingertoppen tracken? 'index' = alleen wijsvinger, voorkomt het
    # ghost-flood in de browser.
    active_finger_tips = (
        {"index": FINGER_TIPS["index"]} if args.fingers == "index"
        else FINGER_TIPS
    )
    log.info("Tracking %d vinger(s) per hand (%s)",
             len(active_finger_tips), ", ".join(active_finger_tips.keys()))

    # ——— System-cursor staat (alleen als --no-cursor NIET is gezet) ————————
    # We laten de primary hand's wijsvinger de fysieke macOS-cursor sturen
    # op het beamer-scherm. Touch-state van diezelfde vinger = mouse_down/up.
    cursor_enabled = not args.no_cursor
    mouse_is_down = False
    last_cursor_pos: tuple[float, float] | None = None
    # Smoothing factor: hoeveel % beweegt de cursor per frame naar het doel toe.
    # 1.0 = direct (jittery), 0.3 = soepel maar 200-300ms lag.
    cursor_smoothing = max(0.05, min(1.0, args.smoothing))
    if cursor_enabled:
        log.info("Systeem-cursor wordt aangedreven door %s-index op (%d,%d)+%dx%d, "
                 "smoothing=%.2f",
                 args.primary_hand, calib.screen_x, calib.screen_y,
                 calib.screen_w, calib.screen_h, cursor_smoothing)

    top = CameraWorker(args.top_idx, "top", args.model,
                       min_confidence=args.min_confidence,
                       width=args.top_width, height=args.top_height, fps=args.top_fps)
    side = CameraWorker(args.side_idx, "side", args.model,
                        min_confidence=args.min_confidence,
                        width=args.side_width, height=args.side_height, fps=args.side_fps)
    top.start()
    side.start()

    log.info("Tracker draait. 'q' in een preview-venster of Ctrl+C om te stoppen.")
    try:
        while True:
            top_frame, top_obs, top_w, top_h = top.snapshot()
            side_frame, side_obs, side_w, side_h = side.snapshot()

            # Voor iedere top-hand: zoek bijpassende side-hand (zelfde handedness),
            # bereken per fingertip touching-status + emit event.
            seen_keys: set[str] = set()
            # Per frame: bepaal welke hand de "primary" is (drijft systeem-cursor).
            # 'auto': pak rechts indien aanwezig, anders eerste; 'R'/'L': forceer.
            primary_label: str | None = None
            if cursor_enabled and top_obs:
                labels = [("L" if h.handedness.lower().startswith("l") else "R")
                          for h in top_obs]
                if args.primary_hand == "auto":
                    primary_label = "R" if "R" in labels else labels[0]
                else:
                    primary_label = args.primary_hand if args.primary_hand in labels else labels[0]

            for hand_obs in top_obs:
                hand_label = "L" if hand_obs.handedness.lower().startswith("l") else "R"
                # Zoek bijpassende side-hand
                side_match = None
                for s in side_obs:
                    s_label = "L" if s.handedness.lower().startswith("l") else "R"
                    if s_label == hand_label:
                        side_match = s
                        break
                # Als geen match: side-touch = False voor elke finger (alles in lucht).
                for finger_name, lm_idx in active_finger_tips.items():
                    if lm_idx >= len(hand_obs.landmarks_px):
                        continue
                    fx, fy = hand_obs.landmarks_px[lm_idx]
                    sx, sy = map_screen((fx, fy), calib, top_w, top_h,
                                        hand_label=hand_label,
                                        finger_name=finger_name,
                                        use_offsets=not args.no_finger_offsets)
                    is_touch = False
                    if side_match is not None and lm_idx < len(side_match.landmarks_px):
                        side_x, side_y = side_match.landmarks_px[lm_idx]
                        is_touch = is_touching_side(
                            side_x, side_y,
                            calib.table_y_pixel, calib.touch_threshold_px,
                            side_zone_bottom=calib.side_zone_bottom,
                            side_zone_top=calib.side_zone_top,
                            _zone_cache=zone_cache,
                        )
                        # ——— Sensor-fusie ————————————————————————————————————
                        # DJI ziet links-rechts (screen-X) goed van bovenaf, maar
                        # de diepte-as (screen-Y, near-far) is in elkaar gedrukt.
                        # De iPhone meet die diepte juist dwars/precies. Dus:
                        # screen-X van de DJI (sx blijft), screen-Y van de iPhone.
                        #
                        # Voorkeur: PER-VINGER iPhone-homografie (calibrate_all_
                        # fingers.py); val terug op de globale side_homography
                        # (calibrate_side_screen.py).
                        # Fusie gebruikt ALLEEN de globale side_homography
                        # (calibrate_side_screen.py). De per-vinger iPhone-data
                        # is tijdelijk uitgeschakeld omdat die de regressie gaf.
                        if args.fusion and calib.side_homography is not None:
                            pt = np.array([[[float(side_x), float(side_y)]]],
                                          dtype=np.float64)
                            out = cv2.perspectiveTransform(pt, calib.side_homography)
                            sy = float(out[0, 0, 1])   # Y uit iPhone
                            # sx blijft van de DJI
                    events = state.observe(
                        hand=hand_label, finger=finger_name,
                        screen_x=sx, screen_y=sy,
                        is_touching=is_touch,
                        palm_facing=hand_obs.palm_facing,
                    )
                    seen_keys.add(f"{hand_label}-{finger_name}")
                    if bridge is not None:
                        for ev in events:
                            bridge.publish(ev)

                    # ——— Systeem-muiscursor aansturen ——————————————————————
                    # Alleen de wijsvinger (index = lm_idx 8) van de primary
                    # hand stuurt de macOS-cursor. sx/sy zijn in scherm-coords
                    # van het kalibratie-display; we voegen de display-offset
                    # erbij voor de globale positie.
                    if (cursor_enabled
                            and finger_name == "index"
                            and hand_label == primary_label):
                        target_x = float(calib.screen_x + sx)
                        target_y = float(calib.screen_y + sy)
                        # Cursor-smoothing: lerp naar target i.p.v. springen.
                        # Geeft soepele beweging ook bij lage MediaPipe-FPS.
                        if last_cursor_pos is None:
                            smooth_x, smooth_y = target_x, target_y
                        else:
                            smooth_x = last_cursor_pos[0] + (target_x - last_cursor_pos[0]) * cursor_smoothing
                            smooth_y = last_cursor_pos[1] + (target_y - last_cursor_pos[1]) * cursor_smoothing
                        # Move alleen als positie genoeg is gewijzigd (>= 1 px)
                        # — vermijdt overspoelen van Quartz event queue.
                        if last_cursor_pos is None or \
                           abs(smooth_x - last_cursor_pos[0]) >= 1 or \
                           abs(smooth_y - last_cursor_pos[1]) >= 1:
                            try:
                                pyautogui.moveTo(int(smooth_x), int(smooth_y), _pause=False)
                                last_cursor_pos = (smooth_x, smooth_y)
                            except Exception:
                                pass
                        # Touch state → mouseDown / mouseUp
                        if is_touch and not mouse_is_down:
                            try:
                                pyautogui.mouseDown(_pause=False)
                                mouse_is_down = True
                            except Exception:
                                pass
                        elif not is_touch and mouse_is_down:
                            try:
                                pyautogui.mouseUp(_pause=False)
                                mouse_is_down = False
                            except Exception:
                                pass

            # Eind-van-frame: fingers die NIET zijn waargenomen krijgen tick.
            for ev in state.tick_missing():
                if bridge is not None:
                    bridge.publish(ev)

            # Safety: als er geen primary hand meer is en de muis hangt nog
            # ingedrukt, laat hem los. Anders blijft de muisknop "vast" tot
            # de gebruiker fysiek met de trackpad klikt.
            if cursor_enabled and mouse_is_down and not top_obs:
                try:
                    pyautogui.mouseUp(_pause=False)
                    mouse_is_down = False
                except Exception:
                    pass

            if args.debug:
                _draw_preview("top", top_frame, top_obs, top.fps())
                _draw_preview("side", side_frame, side_obs, side.fps(),
                              table_y=calib.table_y_pixel,
                              threshold=calib.touch_threshold_px,
                              side_zone_bottom=calib.side_zone_bottom,
                              side_zone_top=calib.side_zone_top)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
            else:
                time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        # Eerst muis loslaten zodat die niet "vast" blijft na Ctrl+C
        if cursor_enabled and mouse_is_down:
            try:
                pyautogui.mouseUp(_pause=False)
            except Exception:
                pass
        top.stop()
        side.stop()
        top.join(timeout=2)
        side.join(timeout=2)
        if bridge is not None:
            bridge.stop()
        if args.debug:
            cv2.destroyAllWindows()
    return 0


HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4), (0,5),(5,6),(6,7),(7,8),
    (5,9),(9,10),(10,11),(11,12), (9,13),(13,14),(14,15),(15,16),
    (13,17),(17,18),(18,19),(19,20), (0,17),
]


def _draw_preview(title: str, frame: np.ndarray | None, obs: list[HandObservation],
                  fps: float, table_y: int | None = None, threshold: int = 0,
                  side_zone_bottom: list[tuple[int, int]] | None = None,
                  side_zone_top: list[tuple[int, int]] | None = None) -> None:
    if frame is None:
        return
    out = frame.copy()
    # Bottom polygon (= touch zone) groen.
    if side_zone_bottom and len(side_zone_bottom) >= 3:
        poly = np.array(side_zone_bottom, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(out, [poly], isClosed=True, color=(0, 220, 0), thickness=2)
    # Top polygon (= 1cm ceiling) oranje.
    if side_zone_top and len(side_zone_top) >= 3:
        poly = np.array(side_zone_top, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(out, [poly], isClosed=True, color=(0, 165, 255), thickness=2)
    for hand in obs:
        col = (0, 200, 255) if hand.handedness == "Right" else (255, 200, 0)
        for a, b in HAND_CONNECTIONS:
            if a < len(hand.landmarks_px) and b < len(hand.landmarks_px):
                pa = tuple(int(v) for v in hand.landmarks_px[a])
                pb = tuple(int(v) for v in hand.landmarks_px[b])
                cv2.line(out, pa, pb, col, 2)
        for finger_name, lm_idx in FINGER_TIPS.items():
            if lm_idx < len(hand.landmarks_px):
                p = tuple(int(v) for v in hand.landmarks_px[lm_idx])
                cv2.circle(out, p, 8, (0, 255, 0), -1)
        wrist = hand.landmarks_px[0] if hand.landmarks_px else None
        if wrist is not None:
            cv2.putText(out, f"{hand.handedness} palm={hand.palm_facing}",
                        (int(wrist[0]) - 30, int(wrist[1]) + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
    if table_y is not None:
        cv2.line(out, (0, table_y), (out.shape[1], table_y), (0, 0, 255), 2)
        if threshold:
            cv2.line(out, (0, table_y - threshold),
                     (out.shape[1], table_y - threshold), (0, 100, 255), 1)
    cv2.putText(out, f"{title}  {fps:.1f} fps",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imshow(f"dual_cam_tracker — {title}", out)


if __name__ == "__main__":
    sys.exit(main())
