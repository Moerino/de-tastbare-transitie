# Backup motor-ESP32 (receiver) — herstelpunt

Gemaakt vlak vóór het flashen van de afgestelde/slimme firmware.

## Wat staat hierin
- **`receiver_flash_2026-06-16_0239_4MB.bin`** — bit-voor-bit dump van de volledige
  4MB flash van de receiver-ESP32 (= Merijn's originele firmware: vaste standen
  64/128/192/255, geen vrije PWM).
  - sha256: `14cc03fcbef694149f6a90f37e2ae5505e9a3a1471ea10161f863099cc5e832a`
- Bijbehorende broncode staat in `../receiver_esp32_ORIGINEEL_merijn.ino`.

## Chip-info
- ESP32-D0WD-V3 (rev v3.1), 4MB flash
- MAC: `d4:e9:f4:c4:10:6c`

## Terugzetten naar deze originele staat
Sluit de receiver via USB aan, zoek de poort (`ls /dev/cu.usbserial-*`), en:

```bash
VENV="/Users/moali/Library/CloudStorage/OneDrive-Hanze/CMD_4/Afstuderen/3. Bestanden Project/tracking/dji_tracker/.venv/bin/python"
"$VENV" -m esptool --port /dev/cu.usbserial-0001 --baud 230400 write_flash 0x0 receiver_flash_2026-06-16_0239_4MB.bin
```

(Gebruik baud 230400 — 460800 gaf serial-ruis op deze chip/kabel.)

Alternatief: flash gewoon `../receiver_esp32_ORIGINEEL_merijn.ino` via de Arduino IDE
voor exact hetzelfde gedrag.
