// audio.js — speelt per voertuig het juiste geluid wanneer het in de maps-app
// geselecteerd wordt. Alle bronbestanden in ./Links/Audio/web/ zijn al naar
// gelijke luidheid (~-16 LUFS) genormaliseerd; het GEWENSTE luidheidsverschil
// per voertuig zit puur in de afspeel-gain hieronder (regelbaar).
//
// Gebruik vanuit app.js:
//   import { vehicleAudio } from "./audio.js";
//   vehicleAudio.playForMode(state.selectedModeId);  // null/onbekend => stilte
//   vehicleAudio.stop();

const AUDIO_DIR = "./Links/Audio/web/";

const FILES = {
  gasoline: "gasoline.mp3",
  plane: "plane.mp3",
  train: "train.mp3",
  hyperloop: "hyperloop.mp3",
};

// ——— Tweakbare luidheidsinstellingen ————————————————————————————————————
// Geluid-dB per voertuig (zelfde waarden als MODE_NOISE_DB in app.js).
const VEHICLE_NOISE_DB = { gasoline: 70, plane: 85, train: 75, hyperloop: 65 };
const LOUDEST_DB = 85;   // referentie (= plane) speelt op 0 dB gain
const SCALE = 0.6;       // 1.0 = volledige dB-spreiding, 0.6 = wat milder
const MASTER_DB = 0;     // algeheel volume erbovenop (verlaag als te hard)
const FADE_SEC = 0.12;   // korte fade in/out bij wisselen (voorkomt clicks)
// ————————————————————————————————————————————————————————————————————————

function dbToGain(db) {
  return Math.pow(10, db / 20);
}

/** Afspeel-gain (lineair) voor een voertuig, afgeleid van zijn geluid-dB. */
function vehicleGain(modeId) {
  const db = VEHICLE_NOISE_DB[modeId];
  if (db == null) return dbToGain(MASTER_DB);
  return dbToGain(MASTER_DB + (db - LOUDEST_DB) * SCALE);
}

class VehicleAudio {
  constructor() {
    this.ctx = null;
    this.buffers = {}; // modeId -> AudioBuffer
    this.current = null; // { modeId, source, gain }
    this.loadingPromise = null;
  }

  /** Maak/hervat de AudioContext. Moet vanuit een user-gesture (klik) komen. */
  _ensureCtx() {
    if (!this.ctx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new Ctx();
    }
    if (this.ctx.state === "suspended") this.ctx.resume();
    return this.ctx;
  }

  /** Laad + decodeer alle voertuigbestanden één keer (gecached). */
  _loadAll() {
    if (this.loadingPromise) return this.loadingPromise;
    const ctx = this._ensureCtx();
    this.loadingPromise = Promise.all(
      Object.entries(FILES).map(async ([modeId, file]) => {
        try {
          const res = await fetch(AUDIO_DIR + file);
          if (!res.ok) throw new Error(`${file}: HTTP ${res.status}`);
          const arr = await res.arrayBuffer();
          this.buffers[modeId] = await ctx.decodeAudioData(arr);
        } catch (err) {
          console.warn("[audio] kon niet laden:", file, err);
        }
      })
    );
    return this.loadingPromise;
  }

  /**
   * Speel het geluid van het geselecteerde voertuig (loopend) op de juiste
   * luidheid. null / onbekend voertuig => stilte. Zelfde voertuig => niks doen.
   */
  async playForMode(modeId) {
    if (!modeId || !FILES[modeId]) {
      this.stop();
      return;
    }
    if (this.current && this.current.modeId === modeId) return;
    const ctx = this._ensureCtx();
    await this._loadAll();
    const buffer = this.buffers[modeId];
    if (!buffer) {
      this.stop();
      return;
    }
    // Selectie kan tijdens het laden alweer gewijzigd zijn; negeer verouderd.
    if (this.current && this.current.modeId === modeId) return;
    this.stop();

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.loop = true;
    const gain = ctx.createGain();
    const target = vehicleGain(modeId);
    const now = ctx.currentTime;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(target, now + FADE_SEC);
    source.connect(gain).connect(ctx.destination);
    source.start();
    this.current = { modeId, source, gain };
  }

  /** Stop het huidige geluid met een korte fade-out. */
  stop() {
    if (!this.current || !this.ctx) {
      this.current = null;
      return;
    }
    const { source, gain } = this.current;
    const now = this.ctx.currentTime;
    try {
      const cur = Math.max(gain.gain.value, 0.0001);
      gain.gain.cancelScheduledValues(now);
      gain.gain.setValueAtTime(cur, now);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + FADE_SEC);
      source.stop(now + FADE_SEC + 0.02);
    } catch (_err) {
      /* source kan al gestopt zijn */
    }
    this.current = null;
  }

  /** Welk voertuig speelt er nu (of null). */
  get currentMode() {
    return this.current ? this.current.modeId : null;
  }
}

export const vehicleAudio = new VehicleAudio();
