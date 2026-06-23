/* ============================================================================
   touch-bridge.js — WebSocket → synthetic PointerEvents
   ============================================================================
   Luistert naar de Python dual-cam tracker op ws://localhost:8765 en zet
   binnenkomende fingertip-events om in echte PointerEvents zodat alle
   bestaande click-handlers, Leaflet pinch-zoom en de on-screen toetsenbord
   triggers werken zonder aanpassing aan de rest van de site.

   Bericht-formaat (JSON, één per regel):
     {
       "type": "pointer",
       "id":   "L-index",          // stabiel per (hand, finger)
       "x":    847,                // screen pixel X
       "y":    523,                // screen pixel Y
       "state":"down" | "move" | "up",
       "hand": "L" | "R",
       "finger":"thumb" | "index" | "middle" | "ring" | "pinky",
       "palm_facing": true
     }

   Visualisatie: per actief pointer-id een kleine cirkel ("ghost cursor") in
   Primary 400 die meebeweegt. Fade-out na 200 ms zonder events.
   ============================================================================ */

(function () {
  "use strict";

  const WS_URL = "ws://localhost:8765";
  const RECONNECT_MS = 1500;
  const GHOST_FADE_MS = 200;

  // Voor reproduceerbare pointerId's per stable string-id.
  const pointerIdMap = new Map();
  let nextPointerId = 1000;

  function getPointerId(stableId) {
    let id = pointerIdMap.get(stableId);
    if (id === undefined) {
      id = nextPointerId++;
      pointerIdMap.set(stableId, id);
    }
    return id;
  }

  // ——— Public meta-map zodat apps de juiste 2 vingers kunnen kiezen ————————
  // Key = pointerId, value = { hand, finger, id, x, y, order }
  // `order` = monotone touch-volgorde: de eerste vinger die het scherm raakt
  // krijgt het laagste getal. Gesture-apps (pinch-demo, kaart) kiezen de 2
  // pointers met de LAAGSTE order = de eerste 2 die hebben aangeraakt,
  // ongeacht welke hand. Dit komt 1-op-1 uit de iPhone side-cam touch-detectie
  // (DOWN-state) die door de tracker wordt doorgegeven.
  window.touchBridgePointers = window.touchBridgePointers || new Map();
  let touchSeq = 0;

  // ——— Ghost-cursor laag ————————————————————————————————————————————————————
  const ghosts = new Map(); // stableId -> {el, lastSeen}
  let ghostLayer = null;

  function ensureGhostLayer() {
    if (ghostLayer) return;
    ghostLayer = document.createElement("div");
    ghostLayer.className = "touch-ghost-layer";
    ghostLayer.style.cssText = [
      "position:fixed",
      "inset:0",
      "pointer-events:none",
      "z-index:10000",
      "overflow:hidden",
    ].join(";");
    document.body.appendChild(ghostLayer);
  }

  function updateGhost(stableId, x, y, state) {
    ensureGhostLayer();
    let g = ghosts.get(stableId);
    if (!g) {
      const el = document.createElement("div");
      el.className = "touch-ghost";
      el.style.cssText = [
        "position:absolute",
        "width:36px",
        "height:36px",
        "margin-left:-18px",
        "margin-top:-18px",
        "border-radius:50%",
        "background:radial-gradient(circle, rgba(247,124,88,0.8) 0%, rgba(247,124,88,0.25) 60%, rgba(247,124,88,0) 100%)",
        "border:2px solid rgba(255,255,255,0.85)",
        "box-shadow:0 0 12px rgba(247,124,88,0.7)",
        "transition:transform 50ms linear, opacity 200ms ease",
        "opacity:1",
      ].join(";");
      ghostLayer.appendChild(el);
      g = { el, lastSeen: 0 };
      ghosts.set(stableId, g);
    }
    g.el.style.transform = `translate(${x}px, ${y}px)`;
    // 'down' = volledige opacity + iets groter; 'move' = idem; 'up' = fade.
    if (state === "up") {
      g.el.style.opacity = "0";
      setTimeout(() => {
        if (g.el.parentNode) g.el.parentNode.removeChild(g.el);
        ghosts.delete(stableId);
      }, GHOST_FADE_MS);
    } else {
      g.el.style.opacity = state === "down" ? "1" : "0.85";
    }
    g.lastSeen = performance.now();
  }

  // ——— Synthetic PointerEvent dispatcher ————————————————————————————————
  // We dispatchen op het element ONDER de coordinaten, met een hele
  // PointerEvent + click-volgorde zodat browsers het als touch-input zien.
  const stateMap = {
    down: ["pointerover", "pointerenter", "pointerdown"],
    move: ["pointermove"],
    up: ["pointerup", "pointerout", "pointerleave"],
  };

  // Track actieve pointers + hun start-target zodat we multi-touch consistent
  // routeren. Bij pinch-zoom in Leaflet moeten BEIDE pointers naar dezelfde
  // map-container — anders ziet Leaflet ze als losse touches en geen pinch.
  const activePointers = new Map();   // pointerId → { target, isPrimary }
  let primaryPointerId = null;

  function pickTarget(msg) {
    const elAtPoint = document.elementFromPoint(msg.x, msg.y);

    // Wanneer er al een andere pointer actief is, probeer een gedeelde
    // ancestor te vinden zodat Leaflet (en andere gesture-libs) ze samen
    // zien. We zoeken eerst naar een Leaflet-container; valt terug op de
    // common ancestor van alle huidige targets; valt terug op elementFromPoint.
    if (activePointers.size === 0) {
      return elAtPoint;
    }

    // Leaflet maps krijgen className 'leaflet-container'. Als één van de
    // huidige actieve pointers (of de nieuwe) op een Leaflet-map staat,
    // route iedereen naar diezelfde map.
    const leafletEl = (elAtPoint && elAtPoint.closest)
      ? elAtPoint.closest(".leaflet-container")
      : null;
    if (leafletEl) return leafletEl;

    for (const p of activePointers.values()) {
      if (p.target && p.target.closest) {
        const lf = p.target.closest(".leaflet-container");
        if (lf) return lf;
      }
    }

    // Anders: common ancestor van de eerste actieve pointer en de nieuwe.
    const firstTarget = activePointers.values().next().value?.target;
    if (firstTarget && elAtPoint) {
      // Simpele ancestor-search: ga van elAtPoint omhoog tot een element dat
      // firstTarget bevat (of omgekeerd). Anders body.
      let node = elAtPoint;
      while (node && !node.contains(firstTarget)) node = node.parentElement;
      if (node) return node;
    }
    return document.body;
  }

  function dispatchPointer(msg) {
    const events = stateMap[msg.state];
    if (!events) return;
    const pointerId = getPointerId(msg.id);

    // Update de publieke meta-map zodat apps weten welke vinger welke is +
    // in welke volgorde ze het scherm raakten.
    if (msg.state === "down") {
      // Nieuwe touch → krijgt het volgende volgnummer (eerste = laagste).
      window.touchBridgePointers.set(pointerId, {
        hand: msg.hand,
        finger: msg.finger,
        id: msg.id,
        x: msg.x,
        y: msg.y,
        order: touchSeq++,
      });
    } else if (msg.state === "move") {
      // Bestaande touch verplaatst → behoud order, update positie.
      const prev = window.touchBridgePointers.get(pointerId);
      if (prev) {
        prev.x = msg.x;
        prev.y = msg.y;
      }
    } else if (msg.state === "up") {
      window.touchBridgePointers.delete(pointerId);
    }

    // Bepaal target: voor 'down' nieuw target kiezen; voor 'move'/'up' gebruik
    // het target dat we bij 'down' hebben vastgehouden (zodat de hele gesture
    // op hetzelfde element blijft, vergelijkbaar met echte touch).
    let target;
    if (msg.state === "down") {
      target = pickTarget(msg);
      const isPrimary = primaryPointerId === null;
      if (isPrimary) primaryPointerId = pointerId;
      activePointers.set(pointerId, { target, isPrimary });
    } else {
      const existing = activePointers.get(pointerId);
      target = existing ? existing.target : pickTarget(msg);
      if (msg.state === "up") {
        activePointers.delete(pointerId);
        if (primaryPointerId === pointerId) primaryPointerId = null;
      }
    }
    if (!target) return;

    const isPrimary = activePointers.get(pointerId)?.isPrimary
      || pointerId === primaryPointerId;

    for (const evType of events) {
      const ev = new PointerEvent(evType, {
        bubbles: true,
        cancelable: true,
        composed: true,
        pointerId,
        pointerType: "touch",
        isPrimary,
        clientX: msg.x,
        clientY: msg.y,
        screenX: msg.x,
        screenY: msg.y,
        button: 0,
        buttons: msg.state === "up" ? 0 : 1,
      });
      target.dispatchEvent(ev);
    }

    // Voor 'up' op een single-finger interactie: vuur ook een echte 'click'
    // op het target. Bij multi-touch SLA we click over — Leaflet pinch
    // gebruikt geen click, en multi-touch click is verwarrend.
    if (msg.state === "up" && activePointers.size === 0) {
      const clickEv = new MouseEvent("click", {
        bubbles: true,
        cancelable: true,
        composed: true,
        clientX: msg.x,
        clientY: msg.y,
        button: 0,
        view: window,
      });
      target.dispatchEvent(clickEv);
    }
  }

  // ——— WebSocket-client met reconnect —————————————————————————————————————
  let ws = null;
  let reconnectTimer = null;

  function connect() {
    try {
      ws = new WebSocket(WS_URL);
    } catch (err) {
      scheduleReconnect();
      return;
    }
    ws.addEventListener("open", () => {
      // eslint-disable-next-line no-console
      console.info("[touch-bridge] verbonden met", WS_URL);
    });
    ws.addEventListener("message", (e) => {
      let msg;
      try {
        msg = JSON.parse(e.data);
      } catch (_) {
        return;
      }
      if (!msg || msg.type !== "pointer") return;
      if (typeof msg.x !== "number" || typeof msg.y !== "number") return;
      updateGhost(msg.id, msg.x, msg.y, msg.state);
      dispatchPointer(msg);
    });
    ws.addEventListener("close", () => {
      scheduleReconnect();
    });
    ws.addEventListener("error", () => {
      // 'error' wordt direct gevolgd door 'close' — reconnect daar.
    });
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, RECONNECT_MS);
  }

  // ——— Public debug-API (voor testen zonder tracker) ——————————————————————
  // Zet `?touch-mock=1` in de URL om een muis-emulatie aan te zetten waarbij
  // elke muisklik wordt vertaald naar synthetic pointer-events. Handig om de
  // bridge te testen zonder Python tracker.
  if (new URLSearchParams(location.search).has("touch-mock")) {
    document.addEventListener("click", (e) => {
      const id = "mock-" + Date.now();
      dispatchPointer({ type: "pointer", id, x: e.clientX, y: e.clientY, state: "down" });
      dispatchPointer({ type: "pointer", id, x: e.clientX, y: e.clientY, state: "up" });
      updateGhost(id, e.clientX, e.clientY, "down");
      setTimeout(() => updateGhost(id, e.clientX, e.clientY, "up"), 80);
    });
    // eslint-disable-next-line no-console
    console.info("[touch-bridge] mock-mode aan (URL ?touch-mock=1)");
  }

  // Verbind direct.
  connect();
})();
