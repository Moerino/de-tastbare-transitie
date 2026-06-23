"""
ws_bridge.py — minimale WebSocket-broadcast voor het dual-cam tracker-script.

Draait in een eigen asyncio-thread zodat de tracker-loop synchroon blijft.
Tracker roept `bridge.publish(dict)` aan vanaf zijn frame-loop; de bridge
zet dat om in JSON en stuurt het naar alle verbonden browser-clients.

Gebruik:
    from ws_bridge import WSBridge
    bridge = WSBridge(host="localhost", port=8765)
    bridge.start()                          # niet-blokkerend, eigen thread
    ...
    bridge.publish({"type":"pointer", ...}) # vanaf elke thread
    ...
    bridge.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Iterable

import websockets
from websockets.server import WebSocketServerProtocol

log = logging.getLogger(__name__)


class WSBridge:
    def __init__(self, host: str = "localhost", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._clients: set[WebSocketServerProtocol] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop_event: asyncio.Event | None = None

    # ——— Publieke API (thread-safe) ————————————————————————————————————————
    def start(self) -> None:
        """Start de WS-server in een achtergrond-thread."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="ws-bridge", daemon=True
        )
        self._thread.start()
        log.info("ws_bridge: started on ws://%s:%d", self.host, self.port)

    def stop(self) -> None:
        """Sluit de server netjes af."""
        if self._loop is None or self._stop_event is None:
            return
        self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def publish(self, message: dict[str, Any]) -> None:
        """Broadcast een bericht naar alle verbonden clients (non-blocking)."""
        if self._loop is None:
            return
        # Serialize hier zodat een bug in `message` direct opvalt, niet in de
        # loop-thread waar exceptions stilletjes verdwijnen.
        try:
            payload = json.dumps(message, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            log.warning("ws_bridge: niet-serialiseerbare publish: %s", exc)
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(payload), self._loop)

    # ——— Interne loop ———————————————————————————————————————————————————————
    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._stop_event = asyncio.Event()
        try:
            loop.run_until_complete(self._serve())
        finally:
            loop.close()

    async def _serve(self) -> None:
        async with websockets.serve(self._on_client, self.host, self.port):
            await self._stop_event.wait()  # type: ignore[union-attr]

    async def _on_client(self, ws: WebSocketServerProtocol) -> None:
        self._clients.add(ws)
        log.info("ws_bridge: client connected (n=%d)", len(self._clients))
        try:
            # We verwachten geen berichten terug — gewoon open houden tot
            # de client zelf de verbinding sluit.
            async for _ in ws:
                pass
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)
            log.info("ws_bridge: client disconnected (n=%d)", len(self._clients))

    async def _broadcast(self, payload: str) -> None:
        if not self._clients:
            return
        # Snapshotten zodat aanpassingen tijdens iteratie geen problemen geven.
        clients: Iterable[WebSocketServerProtocol] = tuple(self._clients)
        await asyncio.gather(
            *(self._safe_send(c, payload) for c in clients),
            return_exceptions=True,
        )

    @staticmethod
    async def _safe_send(ws: WebSocketServerProtocol, payload: str) -> None:
        try:
            await ws.send(payload)
        except websockets.ConnectionClosed:
            pass


# ——— Smoke test bij directe aanroep —————————————————————————————————————
if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    bridge = WSBridge()
    bridge.start()
    print("Open een browser-pagina met touch-bridge.js geladen.")
    print("Druk Ctrl+C om te stoppen.\n")
    try:
        # Stuur elke seconde een pointer-event langs een diagonaal.
        i = 0
        while True:
            x = 200 + (i % 800)
            y = 200 + (i % 600)
            bridge.publish(
                {
                    "type": "pointer",
                    "id": "test-finger",
                    "x": x,
                    "y": y,
                    "state": "move",
                    "hand": "R",
                    "finger": "index",
                    "palm_facing": True,
                }
            )
            time.sleep(0.05)
            i += 12
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
