// motor.js — stuurt de trilmotor aan zodra er een voertuig gekozen wordt in de
// maps-app. Praat met de lokale ESP32-bridge (motor/bridge.py op poort 5001),
// die het commando over serial → ESP-NOW naar de motor-ESP32 stuurt.
//
// Elk voertuig heeft een eigen trilsterkte (vrije PWM-waarde 0-255). Geen
// voertuig / aankomst op de eindbestemming => OFF. De "Haptics"-knop in de UI
// zet de motor aan/uit.
//
// Gebruik vanuit app.js:
//   import { vehicleMotor } from "./motor.js";
//   vehicleMotor.setForMode(state.selectedModeId);  // null/onbekend => OFF
//   vehicleMotor.stop();
//   vehicleMotor.setEnabled(state.hapticsEnabled);

const BRIDGE = "http://127.0.0.1:5001/api/";

// Voertuig → PWM-duty (0-255) van de trilmotor. HIER tweak je het trilgevoel,
// direct in software — geen herflashen meer nodig (de slimme receiver-firmware
// accepteert vrije getallen). Op Hz-volgorde: hyperloop subtiel … auto sterk.
// Motor start al onder PWM 50; deze waarden zijn ruim verdeeld zodat alle vier
// duidelijk van elkaar verschillen.
const MODE_PWM = {
  hyperloop: 60,   // subtiel
  plane: 100,
  train: 140,
  gasoline: 180,   // sterk
};

class VehicleMotor {
  constructor() {
    this.enabled = true;
    this.current = null; // laatst verstuurde PWM-waarde, of null (= uit)
  }

  async _send(cmd) {
    try {
      await fetch(BRIDGE + cmd, { mode: "cors", cache: "no-store" });
    } catch (err) {
      // Bridge draait niet? Niet crashen — alleen loggen.
      console.warn("[motor] bridge niet bereikbaar (draait bridge.py op :5001?)", err);
    }
  }

  /** Zet de motor op de trilsterkte van dit voertuig. null/onbekend => uit. */
  setForMode(modeId) {
    const pwm = MODE_PWM[modeId];
    if (!this.enabled || pwm == null) {
      this.stop();
      return;
    }
    if (this.current === pwm) return; // al op deze sterkte
    this.current = pwm;
    this._send(String(pwm));
  }

  /** Zet de motor uit (één keer; geen herhaalde OFF-spam). */
  stop() {
    if (this.current === null) return;
    this.current = null;
    this._send("OFF");
  }

  /** Haptics aan/uit via de knop in de UI. Uit => meteen stoppen. */
  setEnabled(on) {
    this.enabled = on;
    if (!on) this.stop();
  }

  get currentSpeed() {
    return this.current;
  }
}

export const vehicleMotor = new VehicleMotor();
