import { vehicleAudio } from "./audio.js";
import { vehicleMotor } from "./motor.js";

const CRITERIA = ["co2", "reistijd", "geluid", "trillingen", "afstand"];
const MODES = [
  { id: "gasoline", label: "Benzine auto", className: "gasoline" },
  { id: "plane", label: "Vliegtuig", className: "plane" },
  { id: "train", label: "Trein", className: "train" },
  { id: "hyperloop", label: "Hyperloop", className: "hyperloop" },
];

const DEFAULT_VIEW = {
  center: [52.5, 5.75],
  zoom: 7,
};

const EUROPE_VIEW = {
  center: [51.5, 9.0],
  zoom: 4,
};

/** Compacte kaartweergave in iframe op gevolgen.html (Veendam / regio). */
const PREVIEW_VIEW = {
  center: [53.08, 7.05],
  zoom: 9,
};

const TRANSIT_LAND_API_KEY = "m5CLL5ImRXuP96vSfvKKxZH0Uc683etr";
const TRANSIT_LAND_BASE = "https://www.transit.land/api/v2";
const OSRM_BASE = "https://router.project-osrm.org/route/v1";
const SUGGESTION_LIMIT = 5;
const DEFAULT_PLACE_SUGGESTIONS = [
  "Veendam, Nederland",
  "Groningen, Nederland",
  "Assen, Nederland",
  "Leeuwarden, Nederland",
  "Zwolle, Nederland",
  "Amsterdam, Nederland",
  "Rotterdam, Nederland",
  "Utrecht, Nederland",
  "Brussel, België",
  "Hamburg, Duitsland",
  "Berlijn, Duitsland",
];

// Lokale coördinaten voor de bekende steden in deze app. De publieke Nominatim-
// geocoder blokkeert bursts/parallelle verzoeken; voor de routes die er echt toe
// doen zoeken we daarom eerst hier (direct, geen netwerk, geen rate-limit).
// Nominatim blijft de fallback voor alles wat hier niet in staat.
const KNOWN_PLACES = {
  veendam: [53.0808, 6.8773],
  groningen: [53.2191, 6.568],
  assen: [52.9952, 6.5605],
  leeuwarden: [53.2006, 5.7919],
  zwolle: [52.509, 6.0944],
  amsterdam: [52.3731, 4.8925],
  rotterdam: [51.9244, 4.4778],
  utrecht: [52.0907, 5.1216],
  brussel: [50.8551, 4.3511],
  brussels: [50.8551, 4.3511],
  antwerpen: [51.2211, 4.3997],
  hamburg: [53.5502, 10.0013],
  berlijn: [52.5174, 13.3951],
  berlin: [52.5174, 13.3951],
  emden: [53.3671, 7.2058],
  dortmund: [51.5142, 7.4653],
  hannover: [52.3745, 9.7386],
  leipzig: [51.3406, 12.3747],
  dresden: [51.0493, 13.7381],
  frankfurt: [50.1106, 8.6821],
  neurenberg: [49.4539, 11.0773],
};

/** Zoekt een stad op in KNOWN_PLACES (negeert ", land"-suffix en hoofdletters). */
function lookupKnownPlace(query) {
  if (!query) return null;
  const key = String(query).split(",")[0].trim().toLowerCase();
  return KNOWN_PLACES[key] || null;
}

const HYPERLOOP_RAW_DISTANCES = [
  ["Amsterdam", "Utrecht", 35], ["Amsterdam", "Veendam", 155], ["Amsterdam", "Antwerpen", 130],
  ["Amsterdam", "Brussels", 175], ["Amsterdam", "Hamburg", 380], ["Amsterdam", "Emden", 190],
  ["Amsterdam", "Dortmund", 205], ["Amsterdam", "Hannover", 390], ["Amsterdam", "Berlin", 640],
  ["Amsterdam", "Leipzig", 605], ["Amsterdam", "Dresden", 705], ["Amsterdam", "Frankfurt", 365],
  ["Amsterdam", "Neurenberg", 555], ["Utrecht", "Veendam", 190], ["Utrecht", "Antwerpen", 165],
  ["Utrecht", "Brussels", 150], ["Utrecht", "Hamburg", 410], ["Utrecht", "Emden", 225],
  ["Utrecht", "Dortmund", 175], ["Utrecht", "Hannover", 355], ["Utrecht", "Berlin", 605],
  ["Utrecht", "Leipzig", 570], ["Utrecht", "Dresden", 670], ["Utrecht", "Frankfurt", 330],
  ["Utrecht", "Neurenberg", 520], ["Veendam", "Antwerpen", 290], ["Veendam", "Brussels", 330],
  ["Veendam", "Hamburg", 220], ["Veendam", "Emden", 35], ["Veendam", "Dortmund", 245],
  ["Veendam", "Hannover", 355], ["Veendam", "Berlin", 605], ["Veendam", "Leipzig", 570],
  ["Veendam", "Dresden", 670], ["Veendam", "Frankfurt", 420], ["Veendam", "Neurenberg", 610],
  ["Antwerpen", "Brussels", 40], ["Antwerpen", "Hamburg", 510], ["Antwerpen", "Emden", 325],
  ["Antwerpen", "Dortmund", 340], ["Antwerpen", "Hannover", 520], ["Antwerpen", "Berlin", 770],
  ["Antwerpen", "Leipzig", 735], ["Antwerpen", "Dresden", 835], ["Antwerpen", "Frankfurt", 500],
  ["Antwerpen", "Neurenberg", 685], ["Brussels", "Hamburg", 550], ["Brussels", "Emden", 365],
  ["Brussels", "Dortmund", 320], ["Brussels", "Hannover", 505], ["Brussels", "Berlin", 755],
  ["Brussels", "Leipzig", 720], ["Brussels", "Dresden", 820], ["Brussels", "Frankfurt", 480],
  ["Brussels", "Neurenberg", 665], ["Hamburg", "Emden", 185], ["Hamburg", "Dortmund", 315],
  ["Hamburg", "Hannover", 130], ["Hamburg", "Berlin", 380], ["Hamburg", "Leipzig", 345],
  ["Hamburg", "Dresden", 445], ["Hamburg", "Frankfurt", 495], ["Hamburg", "Neurenberg", 680],
  ["Emden", "Dortmund", 205], ["Emden", "Hannover", 320], ["Emden", "Berlin", 565],
  ["Emden", "Leipzig", 535], ["Emden", "Dresden", 635], ["Emden", "Frankfurt", 385],
  ["Emden", "Neurenberg", 570], ["Dortmund", "Hannover", 185], ["Dortmund", "Berlin", 430],
  ["Dortmund", "Leipzig", 400], ["Dortmund", "Dresden", 500], ["Dortmund", "Frankfurt", 180],
  ["Dortmund", "Neurenberg", 365], ["Hannover", "Berlin", 250], ["Hannover", "Leipzig", 215],
  ["Hannover", "Dresden", 315], ["Hannover", "Frankfurt", 360], ["Hannover", "Neurenberg", 550],
  ["Berlin", "Leipzig", 150], ["Berlin", "Dresden", 250], ["Berlin", "Frankfurt", 445],
  ["Berlin", "Neurenberg", 630], ["Leipzig", "Dresden", 100], ["Leipzig", "Frankfurt", 295],
  ["Leipzig", "Neurenberg", 480], ["Dresden", "Frankfurt", 395], ["Dresden", "Neurenberg", 580],
  ["Frankfurt", "Neurenberg", 185],
];

const HYPERLOOP_DISTANCE_MAP = new Map();
HYPERLOOP_RAW_DISTANCES.forEach(([a, b, d]) => {
  const key = `${a.toLowerCase()}|${b.toLowerCase()}`;
  const reverseKey = `${b.toLowerCase()}|${a.toLowerCase()}`;
  HYPERLOOP_DISTANCE_MAP.set(key, d);
  HYPERLOOP_DISTANCE_MAP.set(reverseKey, d);
});

const HYPERLOOP_CITIES = [...new Set(HYPERLOOP_RAW_DISTANCES.flatMap(([a, b]) => [a, b]))];
const TRANSIT_MODE_FALLBACK_SPEED = {
  walk: 5,
  bus: 30,
  train: 350,
  hyperloop: 1000,
};
const labelToLatLngCache = new Map();

/** Kaart- en legenda-kleuren per mobiliteit (vast palette). */
// Route colors match the corresponding vehicle icon colors.
const MODE_LINE_STYLES = {
  hyperloop: { color: "#2A75BB", weight: 5, opacity: 0.95, dashArray: "10 8" }, // blue
  train:     { color: "#E2B400", weight: 6, opacity: 0.95 },                    // yellow / gold
  plane:     { color: "#E13434", weight: 5, opacity: 0.95, dashArray: "8 6" },  // red
  gasoline:  { color: "#2BA84A", weight: 7, opacity: 0.95 },                    // green
};

/** Indicatieve Hz voor UI-vergelijkbaarheid (geen fysische m/s²→Hz-conversie). */
function scoreToDisplayHz(trillingenScore) {
  return Math.max(0, Math.round(8 + trillingenScore * 65));
}

/** CO₂ (kg), reistijd (min), geluid (dB), trillingen-score voor normalisatie; afstand d = weg-km (referentie). */
function getModePhysics(modeId, distanceKm) {
  const d = distanceKm;
  switch (modeId) {
    case "plane":
      return {
        co2Kg: d * 0.092,
        durationMin: (d / 900) * 60 + 120,
        geluidDb: 85,
        trillingenScore: 0.35,
      };
    case "train":
      return {
        co2Kg: d * 0.008,
        durationMin: (d / 350) * 60 + 30,
        geluidDb: 75,
        trillingenScore: 0.75,
      };
    case "gasoline":
      return {
        co2Kg: d * 0.192,
        durationMin: (d / 110) * 60,
        geluidDb: 70,
        trillingenScore: 1.0,
      };
    case "hyperloop":
      return {
        co2Kg: 0,
        durationMin: (d / 1000) * 60 + 15,
        geluidDb: 65,
        trillingenScore: 0.05,
      };
    default:
      return {
        co2Kg: 0,
        durationMin: 0,
        geluidDb: 70,
        trillingenScore: 0,
      };
  }
}

const state = {
  startPoint: null,
  endPoint: null,
  startLabel: "",
  endLabel: "",
  selectedCriteria: [...CRITERIA],
  routeKm: null,
  selectedModeId: null,
  hapticsEnabled: true,
  uiState: "idle",
  routeDurationMin: null,
  routeType: null,
  routeGeometry: null,
  modeRoutes: null,
  transitRecommendation: "Nog geen OV-analyse",
  transitLines: [],
  history: loadHistory(),
  suggestionEnabled: {
    start: true,
    end: true,
  },
};

class InputAdapter {
  onMove() {}
  onSelect() {}
  onTrackingChange() {}
  start() {}
  stop() {}
}

class MouseAdapter extends InputAdapter {
  constructor(map, callbacks) {
    super();
    this.map = map;
    this.callbacks = callbacks;
    this.longPressTimeoutId = null;
    this.longPressDurationMs = 3000;
    this.pressLatLng = null;
    this.didLongPressSelect = false;
  }

  start() {
    this.map.on("mousemove", (event) => this.callbacks.onMove(event.latlng));
    this.map.on("mousedown", (event) => {
      this.didLongPressSelect = false;
      this.pressLatLng = event.latlng;
      this.clearLongPressTimeout();
      this.longPressTimeoutId = setTimeout(() => {
        if (!this.pressLatLng) return;
        this.didLongPressSelect = true;
        this.callbacks.onSelect(this.pressLatLng);
      }, this.longPressDurationMs);
    });
    this.map.on("mouseup", () => this.cancelPendingLongPress());
    this.map.on("mouseout", () => this.cancelPendingLongPress());
    this.map.on("mousemove", () => {
      if (this.didLongPressSelect) {
        this.didLongPressSelect = false;
      }
    });
  }

  clearLongPressTimeout() {
    if (this.longPressTimeoutId) {
      clearTimeout(this.longPressTimeoutId);
      this.longPressTimeoutId = null;
    }
  }

  cancelPendingLongPress() {
    this.clearLongPressTimeout();
    this.pressLatLng = null;
  }
}

class KinectOneAdapter extends InputAdapter {
  constructor(callbacks) {
    super();
    this.callbacks = callbacks;
  }

  start() {
    // Placeholder: production setup reads websocket depth/cursor events.
    this.callbacks.onTrackingChange(true);
  }
}

class OutputAdapter {
  sendPulse() {}
}

class NoopAdapter extends OutputAdapter {
  sendPulse(_) {}
}

class ArduinoHapticsAdapter extends OutputAdapter {
  constructor(url = "ws://localhost:8765") {
    super();
    this.url = url;
    this.socket = null;
    this.enabled = false;
    this.connect();
  }

  connect() {
    try {
      this.socket = new WebSocket(this.url);
      this.socket.addEventListener("open", () => {
        this.enabled = true;
      });
      this.socket.addEventListener("close", () => {
        this.enabled = false;
      });
      this.socket.addEventListener("error", () => {
        this.enabled = false;
      });
    } catch (_err) {
      this.enabled = false;
    }
  }

  sendPulse(payload) {
    if (!this.enabled || !this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return;
    }
    this.socket.send(JSON.stringify(payload));
  }
}

const isMapEmbedPreview = typeof document !== "undefined" && document.body.classList.contains("map-embed-preview");
const initialMapView = isMapEmbedPreview ? PREVIEW_VIEW : DEFAULT_VIEW;

const map = L.map("map", {
  zoomControl: false,
  attributionControl: false,
  // Multi-touch ondersteuning — Leaflet defaults zijn meestal true maar we
  // zetten ze expliciet zodat synthetic PointerEvents van touch-bridge.js
  // (cameragebaseerde touch) als pinch-zoom worden herkend.
  touchZoom: true,
  bounceAtZoomLimits: false,
  tapTolerance: 15,
  // dragging blijft default (true) zodat single-finger pan ook werkt.
}).setView(initialMapView.center, initialMapView.zoom);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  // Laad een ruime rand tiles ván tevoren in, zodat de hoeken niet grijs
  // flitsen als de kaart een snel voertuig (bijv. hyperloop) volgt.
  keepBuffer: 8,          // standaard 2 — houdt meer tiles buiten beeld geladen
  updateWhenIdle: false,  // blijf tiles laden tijdens het pannen (niet pas erna)
  updateWhenZooming: false,
}).addTo(map);

const layers = {
  startMarker: null,
  endMarker: null,
  routeLine: null,
  modeLines: L.layerGroup().addTo(map),
  modeIcons: L.layerGroup().addTo(map),
};

// ——— Animated vehicle icons along each mode route ————————————————————
//  Time mapping: 15 min travel time -> 60 sec animation (=> 1 min == 4 sec).
//  Runs once per route (no loop). When a mode is selected (focusedModeId set),
//  only that mode's icon animates AND the map pans to follow it; otherwise all
//  available mode icons animate at once.
const MODE_ICON_URLS = {
  gasoline:  "./Links/IMG/icons/gasoline.png",
  plane:     "./Links/IMG/icons/plane.png",
  train:     "./Links/IMG/icons/train.png",
  hyperloop: "./Links/IMG/icons/hyperloop.png",
};
const MODE_ICON_SIZE = 68;          // pixels (2× the previous 34)
const MIN_ANIM_MS    = 2000;        // never animate faster than this (very short trips)
// Max inzoom-niveau tijdens het volgen van een voertuig. Strakker inzoomen laat
// de kaart bij snelle voertuigen (hyperloop) te veel tiles per seconde opvragen
// → de OSM-tileserver throttelt → grijze hoeken. Lager = soepeler maar kleinere
// dB-ringen. Verlaag naar 11 als het nog hapert, verhoog naar 13 voor grotere ringen.
const FOLLOW_MAX_ZOOM = 12;
let modeIconAnimation = null;       // { raf, animators: [...] }

// ——— Noise impact rings ———————————————————————————————————————————
// Inverse-square law for sound in free field:
//   L(r) = L_ref − 20·log10(r / r_ref)
// Solving for the distance where the level drops to an annoyance threshold:
//   r_max = r_ref · 10^((L_source − L_threshold) / 20)
// (= every doubling of distance loses 6 dB.)
//
// WHO night-noise guideline ≈ 40 dB(A). We use 35 dB(A) as the "still
// noticeable at home" cut-off so the visualization is comparative across modes.
const NOISE_REF_DIST_M     = 10;
const NOISE_THRESHOLD_DB   = 35;
const RIPPLE_DURATION_MS   = 2500;  // one ripple grows from 0 to r_max in this time
const RIPPLES_PER_VEHICLE  = 3;     // staggered concentric pulses

// dB at the reference distance, by mode (matches getModePhysics()).
const MODE_NOISE_DB = {
  gasoline:  70,
  plane:     85,
  train:     75,
  hyperloop: 65,
};

function maxNoiseRadiusM(dB) {
  return NOISE_REF_DIST_M * Math.pow(10, (dB - NOISE_THRESHOLD_DB) / 20);
}
let lastModeRoutesKey = null;       // memoization key for drawModeRoutes; voorkomt herstart van iconanimatie

// Coords in this app are a mix: OSRM routes use L.latLng objects, fallbacks may
// be [lat, lng] arrays or {lat, lng} plain objects. Normalize on the fly.
function toLatLng(p) {
  if (!p) return null;
  if (typeof p.lat === "number" && typeof p.lng === "number") return L.latLng(p.lat, p.lng);
  if (Array.isArray(p) && p.length >= 2) return L.latLng(p[0], p[1]);
  return null;
}

function computeCumulativeDistances(coords) {
  const cum = [0];
  for (let i = 1; i < coords.length; i++) {
    const a = toLatLng(coords[i - 1]);
    const b = toLatLng(coords[i]);
    if (!a || !b) { cum.push(cum[i - 1]); continue; }
    cum.push(cum[i - 1] + a.distanceTo(b));
  }
  return cum;
}

function interpolateAlongPath(cum, coords, t) {
  const total = cum[cum.length - 1];
  if (total <= 0 || !Number.isFinite(total)) return toLatLng(coords[0]);
  const target = Math.max(0, Math.min(1, t)) * total;
  let lo = 0, hi = cum.length - 1;
  while (lo + 1 < hi) {
    const mid = (lo + hi) >> 1;
    if (cum[mid] <= target) lo = mid; else hi = mid;
  }
  const segLen = cum[hi] - cum[lo];
  const a = toLatLng(coords[lo]);
  const b = toLatLng(coords[hi]);
  if (!a) return b;
  if (!b || segLen === 0) return a;
  const localT = (target - cum[lo]) / segLen;
  return L.latLng(a.lat + (b.lat - a.lat) * localT, a.lng + (b.lng - a.lng) * localT);
}

function createModeIconMarker(modeId, latlng) {
  return L.marker(toLatLng(latlng) || latlng, {
    interactive: false,
    keyboard: false,
    zIndexOffset: 1000,
    icon: L.icon({
      iconUrl: MODE_ICON_URLS[modeId],
      iconSize: [MODE_ICON_SIZE, MODE_ICON_SIZE],
      iconAnchor: [MODE_ICON_SIZE / 2, MODE_ICON_SIZE / 2],
      className: `mode-icon mode-icon--${modeId}`,
    }),
  });
}

function createNoiseRipples(modeId, latlng) {
  const color = MODE_LINE_STYLES[modeId]?.color || "#fff";
  const center = toLatLng(latlng) || latlng;
  const ripples = [];
  for (let i = 0; i < RIPPLES_PER_VEHICLE; i++) {
    const circle = L.circle(center, {
      radius: 1,
      color,
      weight: 3,
      opacity: 0,
      fillColor: color,
      fillOpacity: 0,
      interactive: false,
    });
    circle.addTo(layers.modeIcons);
    ripples.push({
      circle,
      // Stagger the start of each ripple within one duration so they overlap.
      phaseOffsetMs: (RIPPLE_DURATION_MS / RIPPLES_PER_VEHICLE) * i,
    });
  }
  return ripples;
}

function stopModeIconAnimations() {
  if (modeIconAnimation) {
    cancelAnimationFrame(modeIconAnimation.raf);
    modeIconAnimation = null;
  }
}

function startModeIconAnimations(animators, focusedModeId = null) {
  stopModeIconAnimations();
  if (!animators.length) return;
  const startedAt = performance.now();
  animators.forEach((a) => { a.startTime = startedAt; a.done = false; });

  // Auto-zoom on focused mode so the dB ring is well visible — fit a viewport
  // about 3.5× the ring radius (gives a comfortable margin around the ring).
  if (focusedModeId) {
    const focused = animators.find((a) => a.modeId === focusedModeId);
    if (focused && focused.coords.length > 0) {
      const startLatLng = toLatLng(focused.coords[0]);
      if (startLatLng) {
        try {
          const bounds = startLatLng.toBounds(focused.maxRippleR * 3.5);
          const targetZoom = Math.min(map.getBoundsZoom(bounds), map.getMaxZoom() ?? 18, FOLLOW_MAX_ZOOM);
          map.setView(startLatLng, targetZoom, { animate: true });
        } catch (_e) {
          // toBounds requires Leaflet >= 1.4; fall back to a fixed reasonable zoom.
          map.setView(startLatLng, Math.min(13, FOLLOW_MAX_ZOOM), { animate: true });
        }
      }
    }
  }

  const tick = (now) => {
    let allDone = true;
    animators.forEach((anim) => {
      if (anim.done) return;
      const elapsed = now - anim.startTime;
      let currentLatLng;
      if (elapsed >= anim.durationMs) {
        // Reached the destination — park the icon there, hide ripples, stop.
        currentLatLng = interpolateAlongPath(anim.cumDist, anim.coords, 1);
        anim.marker.setLatLng(currentLatLng);
        anim.currentLatLng = currentLatLng;
        if (anim.ripples) {
          anim.ripples.forEach((r) => r.circle.setStyle({ opacity: 0, fillOpacity: 0 }));
        }
        anim.done = true;
        return;
      }
      const t = elapsed / anim.durationMs;
      currentLatLng = interpolateAlongPath(anim.cumDist, anim.coords, t);
      anim.marker.setLatLng(currentLatLng);
      anim.currentLatLng = currentLatLng;

      // Update noise-impact ripples: each grows from radius 0 -> maxRippleR
      // over RIPPLE_DURATION_MS, fading from opaque to transparent. Multiple
      // ripples are staggered so there's always at least one visible.
      if (anim.ripples) {
        anim.ripples.forEach((r) => {
          const cycle = ((now - anim.startTime + r.phaseOffsetMs) % RIPPLE_DURATION_MS) / RIPPLE_DURATION_MS;
          const radius = Math.max(1, cycle * anim.maxRippleR);
          r.circle.setLatLng(currentLatLng);
          r.circle.setRadius(radius);
          r.circle.setStyle({
            opacity: 0.7 * (1 - cycle),       // ring stroke fades out
            fillOpacity: 0.12 * (1 - cycle),  // soft fill fades out
          });
        });
      }
      allDone = false;
    });

    // Follow-cam: when a single mode is focused, keep its icon centred so the
    // user can comfortably observe the dB rings without manually panning.
    if (focusedModeId) {
      const focused = animators.find((a) => a.modeId === focusedModeId);
      if (focused && focused.currentLatLng && !focused.done) {
        map.setView(focused.currentLatLng, map.getZoom(), { animate: false });
      } else if (focused && focused.done && !focused.audioStopped) {
        // Voertuig is op de eindbestemming aangekomen → geluid + motor stoppen.
        focused.audioStopped = true;
        if (vehicleAudio.currentMode === focusedModeId) vehicleAudio.stop();
        vehicleMotor.stop();
      }
    }

    if (allDone) {
      modeIconAnimation = null;
      return;
    }
    modeIconAnimation = { raf: requestAnimationFrame(tick), animators };
  };
  modeIconAnimation = { raf: requestAnimationFrame(tick), animators };
}

const ui = {
  startInput: document.getElementById("startInput"),
  endInput: document.getElementById("endInput"),
  startSuggestions: document.getElementById("startSuggestions"),
  endSuggestions: document.getElementById("endSuggestions"),
  planRouteBtn: document.getElementById("planRouteBtn"),
  swapBtn: document.getElementById("swapBtn"),
  criteriaChips: document.getElementById("criteriaChips"),
  routeSummary: document.getElementById("routeSummary"),
  comparisonGrid: document.getElementById("comparisonGrid"),
  historyList: document.getElementById("historyList"),
  zoomInBtn: document.getElementById("zoomInBtn"),
  zoomOutBtn: document.getElementById("zoomOutBtn"),
  resetMapBtn: document.getElementById("resetMapBtn"),
  calibrationBtn: document.getElementById("calibrationBtn"),
  calibrationDialog: document.getElementById("calibrationDialog"),
  calibrationNextBtn: document.getElementById("calibrationNextBtn"),
  calibrationCancelBtn: document.getElementById("calibrationCancelBtn"),
  calibrationStepText: document.getElementById("calibrationStepText"),
  calibrationProgressBar: document.getElementById("calibrationProgressBar"),
  toggleHapticsBtn: document.getElementById("toggleHapticsBtn"),
  trackingBanner: document.getElementById("trackingBanner"),
};

const haptics = new ArduinoHapticsAdapter();
const fallbackHaptics = new NoopAdapter();

const inputAdapter = new MouseAdapter(map, {
  onMove: () => {},
  onSelect: (latlng) => {
    if (!state.startPoint) {
      setStartPoint(latlng, "Kaartpunt A");
      return;
    }
    if (!state.endPoint) {
      setEndPoint(latlng, "Kaartpunt B");
      return;
    }
    setStartPoint(latlng, "Kaartpunt A");
    setEndPoint(null, "");
    void renderRoute();
  },
  onTrackingChange: (ok) => {
    state.uiState = ok ? state.uiState : "trackingLost";
    ui.trackingBanner.classList.toggle("hidden", ok);
  },
});

new KinectOneAdapter({
  onTrackingChange: (ok) => {
    ui.trackingBanner.classList.toggle("hidden", ok);
  },
}).start();
inputAdapter.start();

setupUI();
setupLocationSuggestions();
renderCriteria();
renderAll();

window.addEventListener("resize", () => {
  map.invalidateSize();
});
[120, 450, 1100].forEach((ms) => {
  setTimeout(() => map.invalidateSize(), ms);
});
window.addEventListener("message", (event) => {
  if (event.data === "ehc-map-invalidate") {
    map.invalidateSize();
  }
});

function setupUI() {
  ui.planRouteBtn.addEventListener("click", planRouteFromInput);
  ui.swapBtn.addEventListener("click", swapLocations);
  ui.zoomInBtn.addEventListener("click", () => map.zoomIn());
  ui.zoomOutBtn.addEventListener("click", () => map.zoomOut());
  ui.resetMapBtn.addEventListener("click", () => {
    const v = document.body.classList.contains("map-embed-preview") ? PREVIEW_VIEW : DEFAULT_VIEW;
    map.setView(v.center, v.zoom);
  });
  ui.toggleHapticsBtn.addEventListener("click", toggleHaptics);
  ui.calibrationBtn.addEventListener("click", openCalibration);
  ui.calibrationCancelBtn.addEventListener("click", () => ui.calibrationDialog.close());
  ui.calibrationNextBtn.addEventListener("click", advanceCalibration);
}

function setupLocationSuggestions() {
  attachSuggestions(ui.startInput, ui.startSuggestions);
  attachSuggestions(ui.endInput, ui.endSuggestions);
}

function attachSuggestions(inputEl, listEl) {
  let debounceId = null;
  let controller = null;
  let blurTimeoutId = null;

  function renderList(items) {
    const trimmed = items.slice(0, SUGGESTION_LIMIT);
    listEl.innerHTML = "";
    if (!trimmed.length) {
      listEl.hidden = true;
      return;
    }
    trimmed.forEach((place) => {
      const li = document.createElement("li");
      li.className = "suggest-item";
      li.setAttribute("role", "option");
      li.textContent = place;
      // mousedown vuurt vóór blur — zo gaat de selectie niet verloren.
      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        inputEl.value = place;
        listEl.hidden = true;
        inputEl.dispatchEvent(new Event("change", { bubbles: true }));
      });
      listEl.appendChild(li);
    });
    listEl.hidden = false;
  }

  function showDefaults() {
    renderList(DEFAULT_PLACE_SUGGESTIONS);
  }

  inputEl.addEventListener("focus", showDefaults);
  inputEl.addEventListener("click", showDefaults);

  inputEl.addEventListener("input", () => {
    const query = inputEl.value.trim();
    if (debounceId) clearTimeout(debounceId);

    if (!query) {
      showDefaults();
      return;
    }

    // Lokale filter op DEFAULT direct laten zien (snelle feedback),
    // daarna async de live API-resultaten er overheen.
    const localMatch = DEFAULT_PLACE_SUGGESTIONS.filter((p) =>
      p.toLowerCase().includes(query.toLowerCase())
    );
    if (localMatch.length) renderList(localMatch);

    debounceId = setTimeout(async () => {
      if (controller) controller.abort();
      controller = new AbortController();
      const suggestions = await fetchPlaceSuggestions(query, controller.signal);
      const merged = uniq([...suggestions, ...localMatch]).slice(0, SUGGESTION_LIMIT);
      if (merged.length) renderList(merged);
    }, 220);
  });

  inputEl.addEventListener("blur", () => {
    // Kleine vertraging zodat een click op een item nog kan vuren.
    blurTimeoutId = setTimeout(() => {
      listEl.hidden = true;
    }, 150);
  });

  inputEl.addEventListener("focus", () => {
    if (blurTimeoutId) clearTimeout(blurTimeoutId);
  });
}

function renderCriteria() {
  ui.criteriaChips.innerHTML = "";
  CRITERIA.forEach((criterion) => {
    const chip = document.createElement("button");
    chip.className = `chip ${state.selectedCriteria.includes(criterion) ? "active" : ""}`;
    chip.textContent = capitalize(criterion);
    chip.addEventListener("click", () => {
      if (state.selectedCriteria.includes(criterion)) {
        if (state.selectedCriteria.length === 1) return;
        state.selectedCriteria = state.selectedCriteria.filter((item) => item !== criterion);
      } else {
        state.selectedCriteria = [...state.selectedCriteria, criterion];
      }
      renderCriteria();
      renderComparison();
      sendHapticEvent("criterion", criterion, "medium");
    });
    ui.criteriaChips.appendChild(chip);
  });
}

async function planRouteFromInput() {
  const startName = ui.startInput.value.trim();
  const endName = ui.endInput.value.trim();
  if (!startName || !endName) return;

  state.uiState = "selectingLocations";
  // Serieel + via cache: de publieke Nominatim-geocoder blokkeert parallelle
  // bursts (geeft dan "Failed to fetch"). Eén voor één + caching is veilig.
  const start = await geocodeWithCache(startName);
  const end = await geocodeWithCache(endName);
  if (!start || !end) {
    console.warn("[route] geocoding mislukt voor:", !start ? startName : endName);
    return;
  }

  setStartPoint(start, startName);
  setEndPoint(end, endName);
  await renderRoute();
}

function swapLocations() {
  const start = state.startPoint;
  const startLabel = state.startLabel;
  state.startPoint = state.endPoint;
  state.startLabel = state.endLabel;
  state.endPoint = start;
  state.endLabel = startLabel;
  ui.startInput.value = state.startLabel;
  ui.endInput.value = state.endLabel;
  void renderRoute();
}

function setStartPoint(latlng, label) {
  state.startPoint = latlng;
  state.startLabel = label;
  ui.startInput.value = label;
  state.suggestionEnabled.start = false;
  if (layers.startMarker) layers.startMarker.remove();
  if (!latlng) return;
  layers.startMarker = L.marker(latlng).addTo(map).bindPopup(label || "Start");
}

function setEndPoint(latlng, label) {
  state.endPoint = latlng;
  state.endLabel = label;
  ui.endInput.value = label;
  state.suggestionEnabled.end = false;
  if (layers.endMarker) layers.endMarker.remove();
  if (!latlng) return;
  layers.endMarker = L.marker(latlng).addTo(map).bindPopup(label || "Eind");
}

async function renderRoute() {
  if (layers.routeLine) layers.routeLine.remove();
  layers.modeLines.clearLayers();
  layers.modeIcons.clearLayers();
  stopModeIconAnimations();
  if (!state.startPoint || !state.endPoint) {
    state.routeKm = null;
    state.routeDurationMin = null;
    state.routeType = null;
    state.routeGeometry = null;
    state.modeRoutes = null;
    state.transitRecommendation = "Nog geen OV-analyse";
    state.transitLines = [];
    state.uiState = "idle";
    renderAll();
    return;
  }

  const roadRoute = await fetchRoadRoute(state.startPoint, state.endPoint);
  const roadPoints = roadRoute?.coordinates ?? [state.startPoint, state.endPoint];
  const roadDistanceKm = roadRoute?.distanceKm ?? getDistanceKm(state.startPoint, state.endPoint);
  const roadDurationMin = roadRoute?.durationMin ?? (roadDistanceKm / 110) * 60;

  state.modeRoutes = await computeModeRoutes({
    startPoint: state.startPoint,
    endPoint: state.endPoint,
    startLabel: state.startLabel,
    endLabel: state.endLabel,
    roadPoints,
    roadDistanceKm,
  });
  state.selectedModeId = null;
  vehicleAudio.stop(); // nieuwe route => nog niets geselecteerd => stilte
  vehicleMotor.stop(); // ... en motor uit

  const fastestRoute = pickFastestModeRoute(state.modeRoutes);
  if (fastestRoute) {
    state.routeType = getRouteTypeByModeId(fastestRoute.id);
    state.routeKm = fastestRoute.distanceKm;
    state.routeDurationMin = fastestRoute.durationMin;
  } else {
    state.routeType = "road";
    state.routeKm = roadDistanceKm;
    state.routeDurationMin = roadDurationMin;
  }

  const allBounds = drawModeRoutes(state.modeRoutes, state.selectedModeId);
  const selectedGeometry = state.modeRoutes?.[state.selectedModeId || fastestRoute?.id || "gasoline"]?.coordinates;
  state.routeGeometry = selectedGeometry?.length ? selectedGeometry : roadPoints;
  if (allBounds) {
    map.fitBounds(allBounds, { padding: [32, 32] });
  }
  state.uiState = "routeComputed";

  // Update cards immediately after a route is available.
  renderSummary();
  renderComparison();

  await updateTransitInsights(state.startPoint, state.endPoint);

  const entry = {
    id: crypto.randomUUID(),
    start: state.startLabel || "Onbekend",
    end: state.endLabel || "Onbekend",
    distanceKm: state.routeKm,
    timestamp: new Date().toISOString(),
  };
  saveHistoryEntry(entry);
  renderAll();
  const primaryCriterion = getPrimaryCriterion();
  sendHapticEvent("route", primaryCriterion, getImpactLevelForCriterion("gasoline", primaryCriterion));
}

function renderAll() {
  renderSummary();
  renderComparison();
  renderHistory();
}

function renderSummary() {
  const status = state.routeKm ? "Route berekend" : "Nog geen route";
  const distance = state.routeKm ? `${state.routeKm.toFixed(1)} km` : "-";
  const duration = state.routeDurationMin ? `${Math.round(state.routeDurationMin)} min` : "n.v.t.";
  const routeType =
    state.routeType === "hyperloop"
      ? "Hyperloop corridor"
      : state.routeType === "train"
        ? "Treinroute"
        : state.routeType === "road"
          ? "Wegroute"
          : "-";
  const region = map.getZoom() < 6 ? "Europa overzicht" : "Nederland detail";
  const transit = state.transitRecommendation;

  ui.routeSummary.innerHTML = `
    <div><dt>Status</dt><dd>${status}</dd></div>
    <div><dt>Afstand</dt><dd>${distance}</dd></div>
    <div><dt>Reistijd (weg)</dt><dd>${duration}</dd></div>
    <div><dt>Route type</dt><dd>${routeType}</dd></div>
    <div><dt>Regio</dt><dd>${region}</dd></div>
    <div><dt>OV advies</dt><dd>${transit}</dd></div>
  `;
}

function renderComparison() {
  const data = getComparisonData()
    .slice()
    .sort((a, b) => a.impactScore - b.impactScore);
  ui.comparisonGrid.innerHTML = "";
  data.forEach((modeData) => {
    const card = document.createElement("article");
    card.className = `mode-card ${state.selectedModeId === modeData.id ? "selected" : ""} ${
      modeData.impactScore <= 0 ? "hidden" : ""
    }`;
    const selectedCriteria = getSelectedCriteria();
    const metricRows = selectedCriteria
      .map((criterion) => {
        const label = getCriterionLabel(criterion);
        const value = getCriterionValueLabel(modeData, criterion);
        return `<div class="metric-row"><span>${label}</span><strong>${value}</strong></div>`;
      })
      .join("");
    const rankText = `${data.findIndex((item) => item.id === modeData.id) + 1}`;
    const impactColor = getImpactColor(modeData.impactScore);
    const impactTextColor = getImpactTextColor(modeData.impactScore);
    const photo = getModeImageUrl(modeData.id);
    const modeIconUrl = MODE_ICON_URLS[modeData.id];
    card.innerHTML = `
      <div class="mode-card-photo" style="background-image:url('${photo}')">
      <div class="impact-head" style="background:${impactColor};color:${impactTextColor}">
        <img class="mode-card-icon" src="${modeIconUrl}" alt="" aria-hidden="true" />
        <span class="impact-title impact-label">${getCompactModeLabel(modeData.label)}</span>
        <strong class="impact-value">${modeData.impactScore}%</strong>
      </div>
      <div class="mode-card-body">
      ${metricRows}
      <div class="impact-scale" aria-label="Impactscore schaal 0 tot 100">
        <span class="impact-marker" style="left:${modeData.impactScore}%"></span>
      </div>
      </div>
      </div>
    `;
    card.addEventListener("click", () => {
      state.selectedModeId = state.selectedModeId === modeData.id ? null : modeData.id;
      renderComparison();
      sendHapticEvent("mode", modeData.id, getImpactLevelForCriterion(modeData.id, getPrimaryCriterion()));
      // Geluid: geselecteerd voertuig speelt op zijn eigen luidheid; deselectie = stilte.
      vehicleAudio.playForMode(state.selectedModeId);
      // Motor: geselecteerd voertuig trilt op zijn eigen stand; deselectie = uit.
      vehicleMotor.setForMode(state.selectedModeId);
    });
    ui.comparisonGrid.appendChild(card);
  });
  if (state.modeRoutes) {
    drawModeRoutes(state.modeRoutes, state.selectedModeId);
  }
}

function getModeImageUrl(modeId) {
  const byMode = {
    hyperloop: "./Links/IMG/hyperloop-hardt-hyperloop-2.jpeg",
    train: "./Links/IMG/DD-IRM-Teuge(NL)-20090804.jpeg",
    plane: "./Links/IMG/hyperbridge_logo.svg",
    gasoline: "./Links/IMG/2024-12-31-123249669-Benzineauto_is_straks_het_dure_alternatief.jpg",
  };
  return byMode[modeId] || "./Links/IMG/hyperbridge_logo.svg";
}

function getCompactModeLabel(label) {
  return label.replace(" auto", " Auto");
}

function getCriterionLabel(criterion) {
  if (criterion === "co2") return "CO2";
  if (criterion === "reistijd") return "Reistijd";
  if (criterion === "geluid") return "Geluid";
  if (criterion === "trillingen") return "Trillingen";
  if (criterion === "afstand") return "Afstand";
  return capitalize(criterion);
}

function getCriterionValueLabel(modeData, criterion) {
  if (criterion === "co2") return modeData.co2Label;
  if (criterion === "reistijd") return modeData.reistijdLabel;
  if (criterion === "geluid") return modeData.geluidLabel;
  if (criterion === "trillingen") return modeData.trillingenLabel;
  if (criterion === "afstand") return modeData.afstandLabel;
  return "-";
}

function getImpactColor(score) {
  // 0 = groen (links), 100 = rood (rechts).
  const clamped = Math.max(0, Math.min(100, score));
  const hue = 120 - (clamped / 100) * 120;
  return `hsl(${hue}, 85%, 55%)`;
}

function getImpactTextColor(score) {
  return score >= 55 ? "#f8fafc" : "#111827";
}

function getSelectedCriteria() {
  const valid = (state.selectedCriteria || []).filter((criterion) => CRITERIA.includes(criterion));
  return valid.length ? valid : ["co2"];
}

function getPrimaryCriterion() {
  return getSelectedCriteria()[0];
}

function renderHistory() {
  ui.historyList.innerHTML = "";
  if (!state.history.length) {
    const item = document.createElement("li");
    item.textContent = "Nog geen geschiedenis beschikbaar.";
    ui.historyList.appendChild(item);
    return;
  }

  state.history.slice(0, 10).forEach((entry) => {
    const li = document.createElement("li");
    li.className = "history-item";
    li.innerHTML = `
      <div>
        <div><strong>${entry.start}</strong> -> <strong>${entry.end}</strong></div>
        <small>${new Date(entry.timestamp).toLocaleString("nl-NL")} • ${entry.distanceKm.toFixed(1)} km</small>
      </div>
      <button class="btn secondary">Open</button>
    `;
    li.querySelector("button").addEventListener("click", async () => {
      const [start, end] = await Promise.all([geocode(entry.start), geocode(entry.end)]);
      if (start && end) {
        setStartPoint(start, entry.start);
        setEndPoint(end, entry.end);
        await renderRoute();
      }
    });
    ui.historyList.appendChild(li);
  });
}

function getComparisonData() {
  const selectedCriteria = getSelectedCriteria();
  const hasRouteSelected = Boolean(state.startPoint && state.endPoint && state.modeRoutes);

  if (!hasRouteSelected) {
    return MODES.map((mode) => ({
      ...mode,
      afstandLabel: "0.0 km",
      reistijdLabel: "0 min",
      co2Label: "0.0 kg",
      geluidLabel: "0 dB",
      trillingenLabel: "n.v.t.",
      impactScore: 0,
      impacts: {
        co2: 0,
        reistijd: 0,
        geluid: 0,
        trillingen: 0,
        afstand: 0,
      },
    }));
  }

  const refKm = state.modeRoutes?.gasoline?.distanceKm ?? 0;

  return MODES.map((mode) => {
    const physics = getModePhysics(mode.id, refKm);
    const co2Kg = physics.co2Kg;
    const durationMin = physics.durationMin;
    const noiseDb = physics.geluidDb;
    const trillingenScore = physics.trillingenScore;
    const trillingenHz = scoreToDisplayHz(trillingenScore);

    const impacts = {
      co2: normalize(co2Kg, 0, 100),
      reistijd: normalize(durationMin, 10, 400),
      geluid: normalize(noiseDb, 60, 90),
      trillingen: normalize(trillingenScore, 0, 1.2),
      afstand: normalize(refKm, 5, 500),
    };

    const score = Math.round(
      ((impacts.co2 + impacts.reistijd + impacts.geluid + impacts.trillingen + impacts.afstand) / 5) * 100
    );

    return {
      ...mode,
      afstandLabel: `${refKm.toFixed(1)} km`,
      reistijdLabel: `${Math.max(1, Math.round(durationMin))} min`,
      co2Label: `${co2Kg.toFixed(1)} kg`,
      geluidLabel: `${noiseDb} dB`,
      trillingenLabel: `${trillingenHz} Hz`,
      impactScore: score,
      impacts,
    };
  }).sort((a, b) => {
    const aScore =
      selectedCriteria.reduce((sum, criterion) => sum + a.impacts[criterion], 0) / selectedCriteria.length;
    const bScore =
      selectedCriteria.reduce((sum, criterion) => sum + b.impacts[criterion], 0) / selectedCriteria.length;
    return aScore - bScore;
  });
}

function toggleHaptics() {
  state.hapticsEnabled = !state.hapticsEnabled;
  ui.toggleHapticsBtn.textContent = `Haptics: ${state.hapticsEnabled ? "Aan" : "Uit"}`;
  // De motor volgt deze knop: uit => stoppen, aan => weer de huidige keuze.
  vehicleMotor.setEnabled(state.hapticsEnabled);
  if (state.hapticsEnabled) vehicleMotor.setForMode(state.selectedModeId);
}

function sendHapticEvent(type, key, level) {
  if (!state.hapticsEnabled) return;
  const payload = {
    type,
    key,
    level,
    pattern: getHapticPattern(type, key, level),
    timestamp: Date.now(),
  };
  haptics.sendPulse(payload);
  fallbackHaptics.sendPulse(payload);
}

function getHapticPattern(type, key, level) {
  if (type === "criterion" && key === "geluid") return [80, 60, 80];
  if (type === "criterion" && key === "trillingen") return [100, 80, 100, 80];
  if (type === "mode" && key === "hyperloop") return [180, 70, 180];
  if (type === "mode" && key === "plane") return [120, 70, 120, 70];
  if (level === "high") return [220, 100, 220];
  if (level === "medium") return [130, 80];
  return [80];
}

function getImpactLevelForCriterion(modeId, criterion) {
  const mode = getComparisonData().find((x) => x.id === modeId);
  if (!mode) return "low";
  const value = mode.impacts[criterion];
  if (value > 0.66) return "high";
  if (value > 0.33) return "medium";
  return "low";
}

function openCalibration() {
  state.uiState = "calibratingSurface";
  calibrationStep = 0;
  updateCalibrationUI();
  ui.calibrationDialog.showModal();
}

const calibrationSteps = [
  "Wijs naar de linker bovenhoek en houd vast.",
  "Wijs naar de rechter bovenhoek en houd vast.",
  "Wijs naar de rechter onderhoek en houd vast.",
  "Wijs naar de linker onderhoek en houd vast.",
];
let calibrationStep = 0;

function advanceCalibration() {
  calibrationStep += 1;
  if (calibrationStep >= calibrationSteps.length) {
    state.uiState = state.routeKm ? "routeComputed" : "idle";
    ui.calibrationDialog.close();
    return;
  }
  updateCalibrationUI();
}

function updateCalibrationUI() {
  ui.calibrationStepText.textContent = calibrationSteps[calibrationStep];
  ui.calibrationProgressBar.style.width = `${((calibrationStep + 1) / calibrationSteps.length) * 100}%`;
}

function getRouteColorByType(routeType) {
  if (routeType === "hyperloop") return MODE_LINE_STYLES.hyperloop.color;
  if (routeType === "train") return MODE_LINE_STYLES.train.color;
  return MODE_LINE_STYLES.gasoline.color;
}

function buildModeRoutesKey(modeRoutes, focusedModeId) {
  if (!modeRoutes) return "null";
  const parts = ["gasoline", "plane", "train", "hyperloop"].map((id) => {
    const r = modeRoutes[id];
    if (!r?.available || !r.coordinates?.length) return `${id}:_`;
    const first = r.coordinates[0];
    const last = r.coordinates[r.coordinates.length - 1];
    const lat = (p) => (typeof p?.lat === "number" ? p.lat : Array.isArray(p) ? p[0] : 0);
    const lng = (p) => (typeof p?.lng === "number" ? p.lng : Array.isArray(p) ? p[1] : 0);
    return `${id}:${r.coordinates.length}@${lat(first).toFixed(4)},${lng(first).toFixed(4)}->${lat(last).toFixed(4)},${lng(last).toFixed(4)}|${Math.round(r.durationMin || 0)}`;
  });
  return `${focusedModeId || "all"}::${parts.join(";")}`;
}

function drawModeRoutes(modeRoutes, focusedModeId = null) {
  if (!modeRoutes) return null;

  // Voorkom dat een onveranderde re-render de iconanimatie halverwege reset.
  const key = buildModeRoutesKey(modeRoutes, focusedModeId);
  if (key === lastModeRoutesKey && modeIconAnimation) {
    // Niets is veranderd én er loopt nog een animatie: laat alles met rust.
    return layers.modeLines.getLayers().reduce(
      (acc, l) => (typeof l.getBounds === "function" ? (acc ? acc.extend(l.getBounds()) : l.getBounds()) : acc),
      null,
    );
  }
  lastModeRoutesKey = key;

  layers.modeLines.clearLayers();
  layers.modeIcons.clearLayers();
  stopModeIconAnimations();

  const modeOrder = ["gasoline", "plane", "train", "hyperloop"];
  const idsToDraw = focusedModeId ? modeOrder.filter((id) => id === focusedModeId) : modeOrder;

  const bounds = [];
  const animators = [];
  idsToDraw.forEach((modeId) => {
    const route = modeRoutes[modeId];
    if (!route?.available || !route.coordinates?.length) return;
    const base = MODE_LINE_STYLES[modeId] || MODE_LINE_STYLES.gasoline;
    const line = L.polyline(route.coordinates, {
      ...base,
      weight: base.weight + 2,
      opacity: base.opacity,
    });
    line.bindTooltip(`${modeId}: ${Math.round(route.durationMin)} min • ${route.distanceKm.toFixed(1)} km`);
    line.addTo(layers.modeLines);
    drawSegmentLabels(route, modeId);
    bounds.push(line.getBounds());

    // Animated vehicle icon along the polyline.
    // 60 min travel time => 60 sec animation. Loops continuously.
    if (MODE_ICON_URLS[modeId]) {
      const cumDist = computeCumulativeDistances(route.coordinates);
      // Speed mapping: 15 min travel time -> 60 sec animation (4 sec per minute).
      const durationMs = Math.max(MIN_ANIM_MS, (route.durationMin || 60) * 4000);
      const marker = createModeIconMarker(modeId, route.coordinates[0]);
      marker.addTo(layers.modeIcons);
      const ripples = createNoiseRipples(modeId, route.coordinates[0]);
      const maxRippleR = maxNoiseRadiusM(MODE_NOISE_DB[modeId] || 60);
      animators.push({
        modeId, marker, coords: route.coordinates, cumDist, durationMs, startTime: 0,
        ripples, maxRippleR, currentLatLng: null,
      });
    }
  });

  startModeIconAnimations(animators, focusedModeId);

  if (!bounds.length) return null;
  return bounds.reduce((acc, b) => (acc ? acc.extend(b) : b), null);
}

function drawSegmentLabels(route, modeId = "") {
  const segs = (route.segments || []).slice(0, 5);
  segs.forEach((segment) => {
    if (!segment.coordinates?.length) return;
    const midpoint = segment.coordinates[Math.floor(segment.coordinates.length / 2)];
    if (!midpoint) return;
    const chipClass =
      modeId === "train"
        ? "segment-label-chip segment-label-chip--train"
        : modeId === "hyperloop"
          ? "segment-label-chip segment-label-chip--hyperloop"
          : modeId === "plane"
            ? "segment-label-chip segment-label-chip--plane"
            : "segment-label-chip";
    const marker = L.marker(midpoint, {
      interactive: false,
      icon: L.divIcon({
        className: "segment-label-marker",
        html: `<span class="${chipClass}">${segment.label}</span>`,
      }),
    });
    marker.addTo(layers.modeLines);
  });
}

function pickFastestModeRoute(modeRoutes) {
  const candidates = ["gasoline", "plane", "train", "hyperloop"]
    .map((id) => ({ id, ...modeRoutes?.[id] }))
    .filter((route) => route && route.available && Number.isFinite(route.durationMin));
  if (!candidates.length) return null;
  return candidates.sort((a, b) => a.durationMin - b.durationMin)[0];
}

function getRouteTypeByModeId(modeId) {
  if (modeId === "hyperloop") return "hyperloop";
  if (modeId === "train") return "train";
  return "road";
}

function getAccessModeByDistance(distanceKm) {
  return distanceKm <= 1.2 ? "lopen" : "bus";
}

async function computeModeRoutes({ startPoint, endPoint, startLabel, endLabel, roadPoints, roadDistanceKm }) {
  const gasolineDurationMin = getModePhysics("gasoline", roadDistanceKm).durationMin;
  const planeDurationMin = getModePhysics("plane", roadDistanceKm).durationMin;

  const gasolineRoute = {
    available: true,
    type: "road",
    coordinates: roadPoints,
    distanceKm: roadDistanceKm,
    durationMin: gasolineDurationMin,
    segments: [{ mode: "gasoline", label: "benzine auto", coordinates: roadPoints }],
    note: "Directe autoroute",
  };
  const planeRoute = {
    available: true,
    type: "road",
    coordinates: roadPoints,
    distanceKm: roadDistanceKm,
    durationMin: planeDurationMin,
    segments: [{ mode: "plane", label: "vliegtuig", coordinates: roadPoints }],
    note: "Vliegtuigmodel; zelfde referentie-km als de weg.",
  };

  // allSettled in plaats van all — zo trekken de andere modes niet mee neer
  // wanneer één async-pipeline faalt (bv. Transit.land rate-limit).
  const results = await Promise.allSettled([
    computeTrainRoute(startPoint, endPoint, roadDistanceKm),
    computeHyperloopRoute(startPoint, endPoint, startLabel, endLabel, roadDistanceKm),
  ]);

  const [trainResult, hyperloopResult] = results;
  if (trainResult.status === "rejected") {
    console.warn("[routes] computeTrainRoute faalde:", trainResult.reason);
  }
  if (hyperloopResult.status === "rejected") {
    console.warn("[routes] computeHyperloopRoute faalde:", hyperloopResult.reason);
  }

  const trainRoute = trainResult.status === "fulfilled" ? trainResult.value : unavailableRoute("train", roadDistanceKm, "Treinroute mislukt");
  const hyperloopRoute = hyperloopResult.status === "fulfilled" ? hyperloopResult.value : unavailableRoute("hyperloop", roadDistanceKm, "Hyperloop-route mislukt");

  return {
    gasoline: gasolineRoute,
    plane: planeRoute,
    train: trainRoute,
    hyperloop: hyperloopRoute,
  };
}

function unavailableRoute(mode, roadDistanceKm, note) {
  return {
    available: false,
    type: `${mode}-unavailable`,
    coordinates: [],
    distanceKm: roadDistanceKm,
    durationMin: getModePhysics(mode, roadDistanceKm).durationMin,
    segments: [],
    note,
  };
}

async function computeTrainRoute(startPoint, endPoint, roadDistanceKm) {
  const [startRailHub, endRailHub] = await Promise.all([
    findNearestMajorTrainStation(startPoint),
    findNearestMajorTrainStation(endPoint),
  ]);
  // Null-guard zoals bij hyperloop — vermijdt .latlng crash bij ontbrekend station.
  const safeStart = startRailHub && startRailHub.latlng
    ? startRailHub : { name: "start", latlng: startPoint };
  const safeEnd = endRailHub && endRailHub.latlng
    ? endRailHub : { name: "eind", latlng: endPoint };
  if (!startRailHub || !endRailHub) {
    console.warn("[train] geen treinstation gevonden — fallback naar directe punten",
      { startRailHub, endRailHub });
  }

  const directInfo = await fetchDirectTrainOption(safeStart.latlng, safeEnd.latlng);

  const busToRail = await buildPedestrianAccessSegment(startPoint, safeStart.latlng);
  const railMain = await buildSegment(safeStart.latlng, safeEnd.latlng, "train");
  const railToEnd = await buildPedestrianAccessSegment(safeEnd.latlng, endPoint);
  const startBusKm = busToRail.distanceKm;
  const endBusKm = railToEnd.distanceKm;
  const trainMainKm = Math.max(8, railMain.distanceKm || Math.max(8, roadDistanceKm - startBusKm - endBusKm));
  const firstMileMode = "lopen";
  const lastMileMode = "lopen";
  const durationMin = getModePhysics("train", roadDistanceKm).durationMin;

  return {
    available: true,
    type: directInfo.isDirect ? "access-train-access" : "access-train-transfer-access",
    coordinates: mergeCoordinates([busToRail.coordinates, railMain.coordinates, railToEnd.coordinates]),
    distanceKm: startBusKm + trainMainKm + endBusKm,
    durationMin,
    segments: [
      { mode: firstMileMode, label: firstMileMode, coordinates: busToRail.coordinates },
      { mode: "train", label: "trein", coordinates: railMain.coordinates },
      { mode: lastMileMode, label: lastMileMode, coordinates: railToEnd.coordinates },
    ],
    note: directInfo.isDirect
      ? "Eerst naar station, daarna directe treinverbinding"
      : "Eerst naar station, daarna trein met overstap",
  };
}

async function computeHyperloopRoute(startPoint, endPoint, _startLabel, _endLabel, roadDistanceKm) {
  console.debug("[hyperloop] start", { startPoint, endPoint, roadDistanceKm });
  const [startStation, endStation] = await Promise.all([
    findNearestMajorTrainStation(startPoint),
    findNearestMajorTrainStation(endPoint),
  ]);

  // Null-guard: zonder treinstations kunnen we geen access-segment bouwen.
  // Fallback: gebruik de start/eind-punten direct als pseudo-station.
  const safeStartStation = startStation && startStation.latlng
    ? startStation
    : { name: "start", latlng: startPoint };
  const safeEndStation = endStation && endStation.latlng
    ? endStation
    : { name: "eind", latlng: endPoint };
  if (!startStation || !endStation) {
    console.warn("[hyperloop] geen treinstation gevonden — fallback naar directe punten",
      { startStation, endStation });
  }

  const [startHub, endHub] = await Promise.all([
    findNearestHyperloopHub(safeStartStation.latlng),
    findNearestHyperloopHub(safeEndStation.latlng),
  ]);
  if (!startHub || !endHub) {
    console.warn("[hyperloop] geen Hyperloop-hub gevonden", { startHub, endHub });
    return {
      available: false,
      type: "hyperloop-unavailable",
      coordinates: [],
      distanceKm: roadDistanceKm,
      durationMin: getModePhysics("hyperloop", roadDistanceKm).durationMin,
      segments: [],
      note: "Geen Hyperloop-hub in de buurt",
    };
  }

  // Same-hub edge case: pad lengte 1 = getShortestHyperloopPath([startCity]).
  // buildHyperloopPathGeometry retourneert dan lege coords. Voor visuele
  // continuïteit forceren we hier een directe lijn tussen de hub en zichzelf
  // — wat in praktijk neerkomt op "geen Hyperloop-segment nodig, alles via
  // access". We melden dat netjes.
  let cityPath =
    getShortestHyperloopPath(startHub.name, endHub.name) ||
    (getHyperloopDistanceKm(startHub.name, endHub.name) !== null ? [startHub.name, endHub.name] : null);
  const sameHub = startHub.name === endHub.name;
  if (!cityPath?.length || (sameHub && cityPath.length < 2)) {
    if (sameHub) {
      console.info("[hyperloop] start- en eindhub identiek (%s) — directe access-route", startHub.name);
      // Twee identieke hubs → forceer een 2-punts pad zodat de polyline tekent.
      cityPath = [startHub.name, endHub.name];
    } else {
      console.warn("[hyperloop] geen pad tussen hubs", { startHub: startHub.name, endHub: endHub.name });
      return {
        available: false,
        type: "hyperloop-unavailable",
        coordinates: [],
        distanceKm: roadDistanceKm,
        durationMin: getModePhysics("hyperloop", roadDistanceKm).durationMin,
        segments: [],
        note: "Geen directe Hyperloop corridor tussen hubs",
      };
    }
  }

  const toStartStation = await buildPedestrianAccessSegment(startPoint, safeStartStation.latlng);
  const stationToStartHubKm = getDistanceKm(safeStartStation.latlng, startHub.latlng);
  const stationToStartHub =
    stationToStartHubKm > 0.35
      ? await buildSegment(safeStartStation.latlng, startHub.latlng, "bus")
      : { coordinates: [], distanceKm: 0 };

  const mainPath = await buildHyperloopPathGeometry(cityPath);

  const endHubToStationKm = getDistanceKm(endHub.latlng, safeEndStation.latlng);
  const endHubToStation =
    endHubToStationKm > 0.35
      ? await buildSegment(endHub.latlng, safeEndStation.latlng, "bus")
      : { coordinates: [], distanceKm: 0 };

  const fromEndStation = await buildPedestrianAccessSegment(safeEndStation.latlng, endPoint);

  const firstMileMode = "lopen";
  const lastMileMode = "lopen";
  const midStartMode = stationToStartHubKm > 0.35 ? getAccessModeByDistance(stationToStartHubKm) : null;
  const midEndMode = endHubToStationKm > 0.35 ? getAccessModeByDistance(endHubToStationKm) : null;

  const durationMin = getModePhysics("hyperloop", roadDistanceKm).durationMin;

  const distanceKm =
    toStartStation.distanceKm +
    stationToStartHub.distanceKm +
    mainPath.distanceKm +
    endHubToStation.distanceKm +
    fromEndStation.distanceKm;

  const segments = [
    { mode: firstMileMode, label: firstMileMode, coordinates: toStartStation.coordinates },
  ];
  if (stationToStartHub.coordinates?.length) {
    segments.push({
      mode: midStartMode || "bus",
      label: midStartMode || "bus",
      coordinates: stationToStartHub.coordinates,
    });
  }
  segments.push({ mode: "hyperloop", label: "hyperloop", coordinates: mainPath.coordinates });
  if (endHubToStation.coordinates?.length) {
    segments.push({
      mode: midEndMode || "bus",
      label: midEndMode || "bus",
      coordinates: endHubToStation.coordinates,
    });
  }
  segments.push({
    mode: lastMileMode,
    label: lastMileMode,
    coordinates: fromEndStation.coordinates,
  });

  const finalCoords = mergeCoordinates([
    toStartStation.coordinates,
    stationToStartHub.coordinates,
    mainPath.coordinates,
    endHubToStation.coordinates,
    fromEndStation.coordinates,
  ]);

  console.debug("[hyperloop] route gebouwd",
    { coords: finalCoords.length, mainPath: mainPath.coordinates.length,
      startHub: startHub.name, endHub: endHub.name });

  return {
    available: true,
    type: "station-hyperloop-station",
    coordinates: finalCoords,
    distanceKm,
    durationMin,
    segments,
    note: `${safeStartStation.name} → ${startHub.name} → Hyperloop → ${endHub.name} → ${safeEndStation.name}`,
  };
}

async function buildSegment(start, end, mode) {
  if (!start || !end) {
    return { coordinates: [], distanceKm: 0, durationMin: 0 };
  }
  const routed = await fetchRoadRoute(start, end);
  if (routed?.coordinates?.length) {
    return {
      coordinates: routed.coordinates,
      distanceKm: routed.distanceKm,
      durationMin: routed.durationMin,
    };
  }
  const fallback = buildCurvedFallbackCoordinates(start, end);
  return {
    coordinates: fallback,
    distanceKm: getDistanceKm(start, end),
    durationMin: (getDistanceKm(start, end) / TRANSIT_MODE_FALLBACK_SPEED.walk) * 60,
    mode,
  };
}

/** Snelste looproute (OSRM foot) tussen twee punten, o.a. locatie ↔ treinstation. */
async function buildPedestrianAccessSegment(start, end) {
  if (!start || !end) {
    return { coordinates: [], distanceKm: 0, durationMin: 0 };
  }
  const foot = await fetchOsrmRoute(start, end, "foot");
  if (foot?.coordinates?.length) {
    return {
      coordinates: foot.coordinates,
      distanceKm: foot.distanceKm,
      durationMin: foot.durationMin,
    };
  }
  const fallback = buildCurvedFallbackCoordinates(start, end);
  const km = getDistanceKm(start, end);
  return {
    coordinates: fallback,
    distanceKm: km,
    durationMin: (km / TRANSIT_MODE_FALLBACK_SPEED.walk) * 60,
  };
}

function mergeCoordinates(chunks) {
  const merged = [];
  chunks.forEach((chunk) => {
    if (!chunk?.length) return;
    chunk.forEach((point, idx) => {
      if (!point) return;
      if (merged.length && idx === 0) {
        const prev = merged[merged.length - 1];
        if (Math.abs(prev.lat - point.lat) < 1e-6 && Math.abs(prev.lng - point.lng) < 1e-6) return;
      }
      merged.push(point);
    });
  });
  return merged;
}

function buildCurvedFallbackCoordinates(start, end) {
  const midLat = (start.lat + end.lat) / 2;
  const midLng = (start.lng + end.lng) / 2;
  const latDiff = end.lat - start.lat;
  const lngDiff = end.lng - start.lng;
  const scale = 0.16;
  const control = L.latLng(midLat - lngDiff * scale, midLng + latDiff * scale);
  const steps = 24;
  const points = [];
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps;
    const oneMinus = 1 - t;
    const lat = oneMinus * oneMinus * start.lat + 2 * oneMinus * t * control.lat + t * t * end.lat;
    const lng = oneMinus * oneMinus * start.lng + 2 * oneMinus * t * control.lng + t * t * end.lng;
    points.push(L.latLng(lat, lng));
  }
  return points;
}

function resolveHyperloopCityName(label) {
  const norm = normalizeRouteLabel(label);
  if (!norm) return null;
  const found = HYPERLOOP_CITIES.find((city) => city.toLowerCase() === norm);
  return found || null;
}

function getShortestHyperloopPath(startCity, endCity) {
  if (!startCity || !endCity) return null;
  if (startCity === endCity) return [startCity];
  const adjacency = new Map();
  HYPERLOOP_RAW_DISTANCES.forEach(([a, b, d]) => {
    if (!adjacency.has(a)) adjacency.set(a, []);
    if (!adjacency.has(b)) adjacency.set(b, []);
    adjacency.get(a).push({ city: b, dist: d });
    adjacency.get(b).push({ city: a, dist: d });
  });

  const distances = new Map(HYPERLOOP_CITIES.map((city) => [city, Number.POSITIVE_INFINITY]));
  const previous = new Map();
  const visited = new Set();
  distances.set(startCity, 0);

  while (visited.size < HYPERLOOP_CITIES.length) {
    let current = null;
    let best = Number.POSITIVE_INFINITY;
    for (const city of HYPERLOOP_CITIES) {
      if (visited.has(city)) continue;
      const d = distances.get(city);
      if (d < best) {
        best = d;
        current = city;
      }
    }
    if (!current || best === Number.POSITIVE_INFINITY) break;
    visited.add(current);
    if (current === endCity) break;
    for (const { city, dist } of adjacency.get(current) || []) {
      if (visited.has(city)) continue;
      const alt = best + dist;
      if (alt < distances.get(city)) {
        distances.set(city, alt);
        previous.set(city, current);
      }
    }
  }

  if (distances.get(endCity) === Number.POSITIVE_INFINITY) return null;
  const path = [endCity];
  let cursor = endCity;
  while (cursor !== startCity) {
    cursor = previous.get(cursor);
    if (!cursor) return null;
    path.push(cursor);
  }
  return path.reverse();
}

async function buildHyperloopPathGeometry(cityPath) {
  if (!cityPath?.length) return { coordinates: [], distanceKm: 0 };
  const coords = await Promise.all(cityPath.map((city) => geocodeWithCache(city)));
  const valid = coords.filter(Boolean);
  if (valid.length < 2) return { coordinates: [], distanceKm: 0 };

  let distanceKm = 0;
  const chunks = [];
  for (let i = 0; i < valid.length - 1; i += 1) {
    const segment = await buildSegment(valid[i], valid[i + 1], "hyperloop");
    chunks.push(segment.coordinates);
    distanceKm += segment.distanceKm;
  }
  return {
    coordinates: mergeCoordinates(chunks),
    distanceKm,
  };
}

async function geocode(query) {
  // 1) Bekende stad? Direct uit de lokale tabel — geen netwerk, geen rate-limit.
  const local = lookupKnownPlace(query);
  if (local) return L.latLng(local[0], local[1]);

  // 2) Anders Nominatim, met één retry als de geocoder tijdelijk blokkeert
  //    (parallelle bursts geven "Failed to fetch"; even wachten helpt).
  const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}`;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data || !data.length) return null;
      return L.latLng(Number(data[0].lat), Number(data[0].lon));
    } catch (_err) {
      if (attempt === 0) await new Promise((r) => setTimeout(r, 700));
    }
  }
  return null;
}

async function geocodeWithCache(label) {
  const key = normalizeRouteLabel(label);
  if (!key) return null;
  if (labelToLatLngCache.has(key)) return labelToLatLngCache.get(key);
  const latlng = await geocode(label);
  if (latlng) labelToLatLngCache.set(key, latlng);
  return latlng;
}

// Vertaalt Nominatim-landnamen (Engels) naar het Nederlands voor de meest
// voorkomende landen rond de hyperloop-corridor. Andere landen blijven in
// hun originele schrijfwijze staan.
const COUNTRY_NL = {
  Netherlands: "Nederland",
  Belgium: "België",
  Germany: "Duitsland",
  France: "Frankrijk",
  Luxembourg: "Luxemburg",
  "United Kingdom": "Verenigd Koninkrijk",
  Denmark: "Denemarken",
  Poland: "Polen",
  "Czech Republic": "Tsjechië",
  Czechia: "Tsjechië",
  Austria: "Oostenrijk",
  Switzerland: "Zwitserland",
};

// Pakt uit een Nominatim-resultaat het paar "Stad, Land" zoals de
// gebruiker dat verwacht. Voor specifieke adressen (huisnummer + straat)
// blijft de straat zichtbaar zodat de gebruiker zijn exacte adres herkent;
// het land komt er altijd achteraan.
function formatPlaceSuggestion(item) {
  const addr = item.address || {};
  const country = COUNTRY_NL[addr.country] || addr.country || "";
  const city =
    addr.city ||
    addr.town ||
    addr.village ||
    addr.municipality ||
    addr.hamlet ||
    addr.suburb ||
    addr.county ||
    addr.state ||
    "";

  // Als de gebruiker op een specifiek adres zoekt (huisnummer of straat),
  // toon dan straat + huisnummer + stad + land. Anders alleen stad + land.
  const hasStreet = !!(addr.road || addr.pedestrian || addr.cycleway);
  if (hasStreet && city) {
    const street = addr.road || addr.pedestrian || addr.cycleway;
    const num = addr.house_number ? " " + addr.house_number : "";
    const tail = country ? `, ${country}` : "";
    return `${street}${num}, ${city}${tail}`;
  }

  if (city && country) return `${city}, ${country}`;
  if (city) return city;

  // Laatste redmiddel: pak de eerste en laatste segmenten van display_name.
  const parts = (item.display_name || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (parts.length >= 2) return `${parts[0]}, ${parts[parts.length - 1]}`;
  return item.display_name || "";
}

async function fetchPlaceSuggestions(query, signal) {
  try {
    const url =
      `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=10&addressdetails=1&accept-language=nl&q=${encodeURIComponent(
        query
      )}`;
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      signal,
    });
    if (!response.ok) return [];
    const data = await response.json();
    return (data || []).map(formatPlaceSuggestion).filter(Boolean);
  } catch (_err) {
    return [];
  }
}

async function fetchOsrmRoute(start, end, profile = "driving") {
  try {
    const coordinates = `${start.lng},${start.lat};${end.lng},${end.lat}`;
    const url = `${OSRM_BASE}/${profile}/${coordinates}?overview=full&geometries=geojson`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const data = await response.json();
    const route = data?.routes?.[0];
    if (!route?.geometry?.coordinates?.length) return null;

    return {
      coordinates: route.geometry.coordinates.map(([lng, lat]) => L.latLng(lat, lng)),
      distanceKm: route.distance / 1000,
      durationMin: route.duration / 60,
    };
  } catch (_err) {
    return null;
  }
}

async function fetchRoadRoute(start, end) {
  return fetchOsrmRoute(start, end, "driving");
}

async function updateTransitInsights(start, end) {
  const notes = [];
  if (state.modeRoutes?.hyperloop?.note) notes.push(`Hyperloop: ${state.modeRoutes.hyperloop.note}`);
  if (state.modeRoutes?.train?.note) notes.push(`Trein: ${state.modeRoutes.train.note}`);

  const transitFromApi = await fetchTransitLandInsights(start, end);
  if (transitFromApi) {
    const raw = `${transitFromApi.summary}${
      transitFromApi.lines.length ? ` (${transitFromApi.lines.join(", ")})` : ""
    }${notes.length ? ` | ${notes.join(" | ")}` : ""}`;
    state.transitRecommendation = clipUiText(raw);
    state.transitLines = transitFromApi.lines;
    return;
  }

  const fallback = await fetchOverpassTransitFallback(start, end);
  const rawFb = `${fallback.summary}${fallback.lines.length ? ` (${fallback.lines.join(", ")})` : ""}${
    notes.length ? ` | ${notes.join(" | ")}` : ""
  }`;
  state.transitRecommendation = clipUiText(rawFb);
  state.transitLines = fallback.lines;
}

async function fetchTransitLandInsights(start, end) {
  try {
    const [fromStops, toStops] = await Promise.all([fetchTransitLandStops(start), fetchTransitLandStops(end)]);
    if (!fromStops.length || !toStops.length) return null;

    const routesNearStart = await fetchTransitLandRoutesForStops(fromStops);
    const routesNearEnd = await fetchTransitLandRoutesForStops(toStops);
    const startMap = new Map(routesNearStart.map((route) => [route.onestop_id, route]));
    const overlap = routesNearEnd.filter((route) => startMap.has(route.onestop_id));
    const selected = overlap.slice(0, 3);

    if (!selected.length) {
      return {
        summary: "OV mogelijk, maar overstap waarschijnlijk nodig",
        lines: routesNearStart.slice(0, 3).map((route) => route.name || route.short_name || route.onestop_id),
      };
    }

    return {
      summary: `Directe OV-lijn(en) gevonden: ${selected.length}`,
      lines: selected.map((route) => route.name || route.short_name || route.onestop_id),
    };
  } catch (_err) {
    return null;
  }
}

async function fetchTransitLandStops(point, options = {}) {
  const { radius = 2500, limit = 8 } = options;
  const url = new URL(`${TRANSIT_LAND_BASE}/stops`);
  url.searchParams.set("lat", point.lat.toString());
  url.searchParams.set("lon", point.lng.toString());
  url.searchParams.set("radius", String(radius));
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("api_key", TRANSIT_LAND_API_KEY);

  const response = await fetch(url.toString(), { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`TransitLand stops error: ${response.status}`);
  const data = await response.json();
  return data?.stops ?? [];
}

async function fetchTransitLandRoutesForStops(stops) {
  const routeMap = new Map();
  const stopIds = stops.map((stop) => stop.onestop_id).filter(Boolean).slice(0, 4);
  for (const stopId of stopIds) {
    const url = new URL(`${TRANSIT_LAND_BASE}/routes`);
    url.searchParams.set("served_by", stopId);
    url.searchParams.set("limit", "8");
    url.searchParams.set("api_key", TRANSIT_LAND_API_KEY);

    const response = await fetch(url.toString(), { headers: { Accept: "application/json" } });
    if (!response.ok) continue;
    const data = await response.json();
    (data?.routes ?? []).forEach((route) => {
      if (route.onestop_id) routeMap.set(route.onestop_id, route);
    });
  }
  return [...routeMap.values()];
}

async function fetchDirectTrainOption(start, end) {
  try {
    const [startFeeds, endFeeds] = await Promise.all([
      fetchTransitLandFeeds(start),
      fetchTransitLandFeeds(end),
    ]);
    const [fromStops, toStops] = await Promise.all([fetchTransitLandStops(start), fetchTransitLandStops(end)]);
    if (!fromStops.length || !toStops.length || !startFeeds.length || !endFeeds.length) {
      return { isDirect: false, lines: [] };
    }
    const [routesNearStart, routesNearEnd] = await Promise.all([
      fetchTransitLandRoutesForStops(fromStops),
      fetchTransitLandRoutesForStops(toStops),
    ]);
    const startRailMap = new Map(
      routesNearStart.filter((route) => isHeavyRailTrain(route)).map((route) => [route.onestop_id, route])
    );
    const overlap = routesNearEnd
      .filter((route) => isHeavyRailTrain(route) && startRailMap.has(route.onestop_id))
      .slice(0, 3);
    return {
      isDirect: overlap.length > 0,
      lines: overlap.map((route) => route.name || route.short_name || route.onestop_id),
    };
  } catch (_err) {
    return { isDirect: false, lines: [] };
  }
}

async function fetchTransitLandFeeds(point) {
  try {
    const url = new URL(`${TRANSIT_LAND_BASE}/feeds`);
    url.searchParams.set("lat", point.lat.toString());
    url.searchParams.set("lon", point.lng.toString());
    url.searchParams.set("radius", "30000");
    url.searchParams.set("limit", "12");
    url.searchParams.set("api_key", TRANSIT_LAND_API_KEY);
    const response = await fetch(url.toString(), { headers: { Accept: "application/json" } });
    if (!response.ok) return [];
    const data = await response.json();
    return data?.feeds ?? [];
  } catch (_err) {
    return [];
  }
}

function isHeavyRailTrain(route) {
  return String(route?.route_type) === "2";
}

function majorStationNameScore(name) {
  const n = String(name || "").toLowerCase();
  let score = 0;
  if (/(hoofd|centraal|central|hbf|haupt|main|spoor|station)/i.test(n)) score += 40;
  if (/(groningen|amsterdam|utrecht|berlin|hamburg|frankfurt|brussel|brussels)/i.test(n)) score += 8;
  return score;
}

async function nominatimNearestRailStation(point) {
  try {
    const pad = 0.12;
    const viewbox = `${point.lng - pad},${point.lat + pad},${point.lng + pad},${point.lat - pad}`;
    let cityQuery = "railway station";
    try {
      const revUrl = `https://nominatim.openstreetmap.org/reverse?format=json&lat=${point.lat}&lon=${point.lng}`;
      const revRes = await fetch(revUrl, { headers: { Accept: "application/json" } });
      const rev = await revRes.json();
      const city =
        rev.address?.city ||
        rev.address?.town ||
        rev.address?.village ||
        rev.address?.municipality ||
        rev.address?.state;
      if (city) cityQuery = `${city} railway station`;
    } catch (_e) {
      // keep default query
    }
    const url = `https://nominatim.openstreetmap.org/search?format=json&limit=12&bounded=1&viewbox=${viewbox}&q=${encodeURIComponent(
      cityQuery
    )}`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return { name: "Station", latlng: point };
    const results = await response.json();
    if (!Array.isArray(results) || !results.length) {
      return { name: "Station", latlng: point };
    }
    let best = null;
    let bestDist = Number.POSITIVE_INFINITY;
    for (const item of results) {
      const lat = Number(item.lat);
      const lon = Number(item.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      const latlng = L.latLng(lat, lon);
      const d = getDistanceKm(point, latlng);
      if (d < bestDist) {
        bestDist = d;
        best = { name: item.display_name?.split(",")[0]?.trim() || "Station", latlng };
      }
    }
    return best || { name: "Station", latlng: point };
  } catch (_err) {
    return { name: "Station", latlng: point };
  }
}

async function resolveWalkingStationTarget(stopMeta, userPoint) {
  try {
    const baseName = stopMeta?.name || "railway station";
    let cityQuery = "";
    try {
      const revUrl = `https://nominatim.openstreetmap.org/reverse?format=json&lat=${userPoint.lat}&lon=${userPoint.lng}`;
      const revRes = await fetch(revUrl, { headers: { Accept: "application/json" } });
      const rev = await revRes.json();
      const city =
        rev.address?.city ||
        rev.address?.town ||
        rev.address?.village ||
        rev.address?.municipality ||
        rev.address?.state;
      if (city) {
        cityQuery = `${city} centraal station`;
      }
    } catch (_e) {
      // Use fallback query only.
    }

    const pad = 0.08;
    const anchor = stopMeta?.latlng || userPoint;
    const viewbox = `${anchor.lng - pad},${anchor.lat + pad},${anchor.lng + pad},${anchor.lat - pad}`;
    const query = cityQuery || `${baseName} railway station`;
    const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=8&bounded=1&viewbox=${viewbox}&q=${encodeURIComponent(
      query
    )}`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return stopMeta;
    const results = await response.json();
    if (!Array.isArray(results) || !results.length) return stopMeta;

    let best = stopMeta;
    let bestCost = Number.POSITIVE_INFINITY;
    for (const item of results) {
      const lat = Number(item.lat);
      const lon = Number(item.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      const candidate = L.latLng(lat, lon);
      const foot = await fetchOsrmRoute(userPoint, candidate, "foot");
      const walkMin = foot?.durationMin ?? (getDistanceKm(userPoint, candidate) / TRANSIT_MODE_FALLBACK_SPEED.walk) * 60;
      const toStopKm = stopMeta?.latlng ? getDistanceKm(candidate, stopMeta.latlng) : 0;
      const stationBias = /(centraal|central|hauptbahnhof|hbf|station)/i.test(item.display_name || "") ? -3 : 0;
      const cost = walkMin + toStopKm * 2 + stationBias;
      if (cost < bestCost) {
        bestCost = cost;
        best = {
          name: item.display_name?.split(",")[0]?.trim() || stopMeta?.name || "Station",
          latlng: candidate,
        };
      }
    }
    return best || stopMeta;
  } catch (_err) {
    return stopMeta;
  }
}

async function findNearestMajorTrainStation(point) {
  const candidates = [];
  try {
    const stops = await fetchTransitLandStops(point, { radius: 22000, limit: 45 });
    for (const stop of stops) {
      const stopPoint = extractStopLatLng(stop);
      if (!stopPoint) continue;
      const routes = await fetchTransitLandRoutesForStops([stop]);
      if (!routes.some((route) => isHeavyRailTrain(route))) continue;
      const haversineKm = getDistanceKm(point, stopPoint);
      const nameScore = majorStationNameScore(stop.name);
      candidates.push({
        name: stop.name || stop.onestop_id || "Treinstation",
        latlng: stopPoint,
        haversineKm,
        nameScore,
        sortKey: nameScore - haversineKm * 1.8,
      });
    }
  } catch (_err) {
    // fall through
  }

  if (!candidates.length) {
    return nominatimNearestRailStation(point);
  }

  candidates.sort((a, b) => b.sortKey - a.sortKey);
  const top = candidates.slice(0, 12);

  let best = top[0];
  let bestWalkMin = Number.POSITIVE_INFINITY;
  for (const c of top) {
    const foot = await fetchOsrmRoute(point, c.latlng, "foot");
    const walkMin = foot?.durationMin ?? (c.haversineKm / TRANSIT_MODE_FALLBACK_SPEED.walk) * 60;
    const tieBetter =
      Math.abs(walkMin - bestWalkMin) <= 0.5 &&
      (c.nameScore > best.nameScore ||
        (c.nameScore === best.nameScore && c.haversineKm + 1e-6 < best.haversineKm));
    if (walkMin < bestWalkMin - 0.5 || tieBetter) {
      bestWalkMin = walkMin;
      best = c;
    }
  }

  const snapped = await resolveWalkingStationTarget(best, point);
  return snapped || { name: best.name, latlng: best.latlng };
}

async function findNearestHyperloopHub(point) {
  const cityPoints = await Promise.all(
    HYPERLOOP_CITIES.map(async (city) => {
      const latlng = await geocodeWithCache(city);
      if (!latlng) return null;
      return { name: city, latlng };
    })
  );
  const candidates = cityPoints.filter(Boolean);
  if (!candidates.length) return null;
  let best = null;
  for (const candidate of candidates) {
    const distanceKm = getDistanceKm(point, candidate.latlng);
    if (!best || distanceKm < best.distanceKm) {
      best = { ...candidate, distanceKm };
    }
  }
  return best;
}

function extractStopLatLng(stop) {
  const coords = stop?.geometry?.coordinates;
  if (Array.isArray(coords) && coords.length >= 2) {
    return L.latLng(Number(coords[1]), Number(coords[0]));
  }
  if (stop?.location && Array.isArray(stop.location) && stop.location.length >= 2) {
    return L.latLng(Number(stop.location[1]), Number(stop.location[0]));
  }
  if (typeof stop?.lat === "number" && typeof stop?.lon === "number") {
    return L.latLng(stop.lat, stop.lon);
  }
  return null;
}

async function fetchOverpassTransitFallback(start, end) {
  const box = toBoundingBox(start, end, 0.18);
  const query = `
    [out:json][timeout:25];
    (
      relation["route"="train"](${box});
      relation["route"="tram"](${box});
      relation["route"="subway"](${box});
      relation["route"="bus"](${box});
    );
    out tags 25;
  `;
  try {
    const response = await fetch("https://overpass-api.de/api/interpreter", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
      body: `data=${encodeURIComponent(query)}`,
    });
    if (!response.ok) throw new Error("Overpass failed");
    const data = await response.json();
    const lines = (data?.elements ?? [])
      .map((element) => element.tags?.name || element.tags?.ref || element.tags?.route)
      .filter(Boolean)
      .slice(0, 5);

    if (!lines.length) {
      return { summary: "Geen OV-lijnen gevonden in routecorridor", lines: [] };
    }
    return { summary: "OV-corridor gevonden", lines };
  } catch (_err) {
    return { summary: "Transit-land niet bereikbaar; fallback zonder OV-lijnen", lines: [] };
  }
}

function toBoundingBox(start, end, padding) {
  const minLat = Math.min(start.lat, end.lat) - padding;
  const minLon = Math.min(start.lng, end.lng) - padding;
  const maxLat = Math.max(start.lat, end.lat) + padding;
  const maxLon = Math.max(start.lng, end.lng) + padding;
  return `${minLat},${minLon},${maxLat},${maxLon}`;
}

function getDistanceKm(a, b) {
  const meters = map.distance(a, b);
  return meters / 1000;
}

function normalize(value, min, max) {
  const n = (value - min) / (max - min);
  return Math.max(0, Math.min(1, n));
}

/** Zichtbare UI-teksten max. 200 tekens (incl. dynamische OV-string). */
function clipUiText(text, maxLen = 200) {
  if (!text) return "";
  if (text.length <= maxLen) return text;
  return `${text.slice(0, maxLen - 1)}…`;
}

function normalizeRouteLabel(label) {
  if (!label) return "";
  const base = label.split(",")[0].trim().toLowerCase();
  if (base === "brussel") return "brussels";
  if (base === "berlijn") return "berlin";
  if (base === "neurenburg") return "neurenberg";
  return base;
}

function getHyperloopDistanceKm(startLabel, endLabel) {
  const start = normalizeRouteLabel(startLabel);
  const end = normalizeRouteLabel(endLabel);
  if (!start || !end || start === end) return null;
  const key = `${start}|${end}`;
  return HYPERLOOP_DISTANCE_MAP.has(key) ? HYPERLOOP_DISTANCE_MAP.get(key) : null;
}

function capitalize(word) {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

function uniq(items) {
  return [...new Set(items)];
}

function loadHistory() {
  const raw = localStorage.getItem("mobility-history");
  if (!raw) return [];
  try {
    return JSON.parse(raw);
  } catch (_err) {
    return [];
  }
}

function saveHistoryEntry(entry) {
  const exists = state.history.find((item) => item.start === entry.start && item.end === entry.end);
  if (exists) return;
  state.history.unshift(entry);
  localStorage.setItem("mobility-history", JSON.stringify(state.history.slice(0, 20)));
}

window.__debug = {
  setEuropeView: () => map.setView(EUROPE_VIEW.center, EUROPE_VIEW.zoom),
  setDefaultView: () => {
    const v = document.body.classList.contains("map-embed-preview") ? PREVIEW_VIEW : DEFAULT_VIEW;
    map.setView(v.center, v.zoom);
  },
};
