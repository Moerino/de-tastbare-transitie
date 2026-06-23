"""
touch_state.py — per-finger state machine + cursor-smoothing.

Verantwoordelijk voor:
  1. One Euro Filter: cursor-jitter dempen zonder merkbare lag.
  2. State machine per (hand, finger)-paar:  IDLE → HOVER → DOWN → UP → IDLE
     Met N opeenvolgende frames vereist per transitie om flikkeringen te
     dempen.
  3. Bouwen van WS-events bij elke transitie of move.

De top-cam levert X/Y (in scherm-pixels na homography), de side-cam levert
een boolean `is_touching` per fingertip. Beide worden hier samengevoegd tot
één state per finger.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

# ——— One Euro Filter ————————————————————————————————————————————————————
# Referentie: Casiez et al. 2012. https://gery.casiez.net/1euro/
# Compacte vertaling — geen externe dependency, ~30 regels werk.


class _LowPass:
    def __init__(self) -> None:
        self.y: float | None = None
        self.s: float | None = None

    def __call__(self, x: float, alpha: float) -> float:
        if self.s is None:
            self.s = x
        else:
            self.s = alpha * x + (1.0 - alpha) * self.s
        self.y = x
        return self.s


class OneEuroFilter:
    def __init__(
        self,
        mincutoff: float = 0.2,   # was 0.4 (en eerder 1.0) — halve cutoff = ~2x soepeler
        beta: float = 0.15,        # was 0.10 — iets hoger om snelle beweging responsief te houden
        dcutoff: float = 1.0,
    ) -> None:
        self.mincutoff = mincutoff
        self.beta = beta
        self.dcutoff = dcutoff
        self._x = _LowPass()
        self._dx = _LowPass()
        self._last_time: float | None = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        # Tau = 1/(2 pi cutoff); alpha = 1/(1 + tau/dt)
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x: float, t: float | None = None) -> float:
        if t is None:
            t = time.monotonic()
        if self._last_time is None:
            self._last_time = t
            return self._x(x, 1.0)
        dt = max(1e-6, t - self._last_time)
        self._last_time = t
        # Schat de afgeleide
        prev_x = self._x.y if self._x.y is not None else x
        dx = (x - prev_x) / dt
        edx = self._dx(dx, self._alpha(self.dcutoff, dt))
        cutoff = self.mincutoff + self.beta * abs(edx)
        return self._x(x, self._alpha(cutoff, dt))


class XYFilter:
    """Twee One Euro Filters, één voor X en één voor Y."""

    def __init__(self, mincutoff: float = 0.2, beta: float = 0.15) -> None:
        # ~2x soepeler dan vorige defaults (was 0.4, 0.10). Cursor staat
        # vrijwel stil bij stilstaande hand. Beta iets verhoogd zodat snelle
        # bewegingen niet laggy worden. Tune via tracker CLI als nodig.
        self.fx = OneEuroFilter(mincutoff=mincutoff, beta=beta)
        self.fy = OneEuroFilter(mincutoff=mincutoff, beta=beta)

    def __call__(self, x: float, y: float, t: float | None = None) -> tuple[float, float]:
        if t is None:
            t = time.monotonic()
        return self.fx(x, t), self.fy(y, t)


# ——— State machine ——————————————————————————————————————————————————————
IDLE = "idle"
HOVER = "hover"
DOWN = "down"


@dataclass
class FingerState:
    """State + filter voor één (hand, finger)-paar."""

    key: str                       # bv. "L-index"
    hand: str                      # "L" / "R"
    finger: str                    # "thumb" / "index" / "middle" / "ring" / "pinky"
    state: str = IDLE
    touching_frames: int = 0       # opeenvolgende frames "is_touching=True"
    not_touching_frames: int = 0   # opeenvolgende frames False
    missing_frames: int = 0        # frames waarin top-cam de finger niet zag
    x: float = 0.0
    y: float = 0.0
    palm_facing: bool = True
    filter: XYFilter = field(default_factory=XYFilter)

    def update_position(self, raw_x: float, raw_y: float) -> None:
        self.x, self.y = self.filter(raw_x, raw_y)
        self.missing_frames = 0


class TouchStateTracker:
    """Houdt per finger de state bij + produceert events op transities.

    Parameters
    ----------
    down_threshold_frames : int
        Aantal opeenvolgende `is_touching=True`-frames vereist voor HOVER→DOWN.
    up_threshold_frames : int
        Aantal opeenvolgende `False`-frames vereist voor DOWN→HOVER.
    missing_timeout_frames : int
        Hoeveel frames een finger ongezien mag zijn voordat we hem als IDLE
        markeren (en dus een 'up'-event sturen als hij DOWN was).
    """

    def __init__(
        self,
        down_threshold_frames: int = 2,
        up_threshold_frames: int = 2,
        missing_timeout_frames: int = 6,
        smoothing_cutoff: float = 0.2,
        smoothing_beta: float = 0.15,
    ) -> None:
        self.down_threshold = down_threshold_frames
        self.up_threshold = up_threshold_frames
        self.missing_timeout = missing_timeout_frames
        # Tune-bare smoothing-params, gedeeld door alle FingerState-filters.
        self._smoothing_cutoff = smoothing_cutoff
        self._smoothing_beta = smoothing_beta
        self._fingers: dict[str, FingerState] = {}

    def _get_or_create(self, hand: str, finger: str) -> FingerState:
        key = f"{hand}-{finger}"
        f = self._fingers.get(key)
        if f is None:
            f = FingerState(
                key=key, hand=hand, finger=finger,
                filter=XYFilter(mincutoff=self._smoothing_cutoff,
                                beta=self._smoothing_beta),
            )
            self._fingers[key] = f
        return f

    def observe(
        self,
        hand: str,
        finger: str,
        screen_x: float,
        screen_y: float,
        is_touching: bool,
        palm_facing: bool = True,
    ) -> list[dict]:
        """Registreer één frame-observatie. Geeft eventuele WS-events terug."""
        f = self._get_or_create(hand, finger)
        f.update_position(screen_x, screen_y)
        f.palm_facing = palm_facing

        events: list[dict] = []
        if is_touching:
            f.touching_frames += 1
            f.not_touching_frames = 0
        else:
            f.not_touching_frames += 1
            f.touching_frames = 0

        # Transities
        if f.state == IDLE:
            # Eerste keer dat we de finger zien — emit hover (visueel).
            f.state = HOVER
            events.append(self._event(f, "move"))
        elif f.state == HOVER:
            if f.touching_frames >= self.down_threshold:
                f.state = DOWN
                events.append(self._event(f, "down"))
            else:
                events.append(self._event(f, "move"))
        elif f.state == DOWN:
            if f.not_touching_frames >= self.up_threshold:
                f.state = HOVER
                events.append(self._event(f, "up"))
            else:
                events.append(self._event(f, "move"))
        return events

    def tick_missing(self) -> list[dict]:
        """Verwerk fingers die in deze frame NIET zijn waargenomen.

        Aanroepen aan het eind van elk frame nadat alle observe()-calls binnen
        zijn. Stuurt automatisch 'up'-events voor fingers die te lang weg zijn.
        """
        events: list[dict] = []
        to_remove: list[str] = []
        for f in self._fingers.values():
            f.missing_frames += 1
            if f.missing_frames < self.missing_timeout:
                continue
            if f.state == DOWN:
                events.append(self._event(f, "up"))
            to_remove.append(f.key)
        for k in to_remove:
            del self._fingers[k]
        return events

    @staticmethod
    def _event(f: FingerState, state: str) -> dict:
        return {
            "type": "pointer",
            "id": f.key,
            "x": int(round(f.x)),
            "y": int(round(f.y)),
            "state": state,
            "hand": f.hand,
            "finger": f.finger,
            "palm_facing": f.palm_facing,
        }


# ——— Smoke test ——————————————————————————————————————————————————————————
if __name__ == "__main__":
    t = TouchStateTracker(down_threshold_frames=2, up_threshold_frames=2)
    # Simuleer een vinger die langzaam beweegt en op frame 5 de tafel raakt.
    for i in range(10):
        evs = t.observe(
            hand="R",
            finger="index",
            screen_x=100 + i * 5,
            screen_y=200,
            is_touching=(4 <= i <= 7),
        )
        for e in evs:
            print(f"frame {i}: {e}")
