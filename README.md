# HyperBRIDGE

Een interactieve installatie die aanvoelt als een grote multi-touch iPad. Een beamer
projecteert (als 2e scherm van een MacBook) een website op een wit bord op tafel. Twee
camera's tracken je hand, zodat je de geprojecteerde site bedient met je vingers (wijzen
+ pinch = klik). Kies je in de maps-app een vervoersmiddel, dan speelt het bijbehorende
geluid af én trilt een fysieke motor met een bijpassende sterkte.

> Afstudeerproject (CMD). Werkt op **macOS** (gebruikt AVFoundation-camera's en de
> Quartz/PyAutoGUI-cursor-API).

---

## Hoe het werkt

```
DJI Action 5 Pro (top-view) ─► MediaPipe hand-tracking ─► macOS-cursor (wijzen)
                                                          pinch / vuist = klik

maps-app (browser) ─► voertuigkeuze ─┬─► audio.js   (geluid in de browser)
                                     └─► motor.js ─► bridge.py (Flask :5001)
                                                     ─► ESP32 (USB → ESP-NOW) ─► trilmotor
```

De handtracking stuurt de echte muiscursor aan; de website reageert daar gewoon op als
op muis/touch. Een aparte Flask-bridge stuurt per voertuig een trilsterkte naar een ESP32
die een DC-trilmotor aanstuurt.

---

## Repo-structuur

```
.
├── README.md                 (dit bestand)
├── requirements.txt          (Python-afhankelijkheden, macOS / Python 3.12)
├── website/                  (de site: HTML/JS/CSS + media in Links/)
│   └── src/                  (app.js, motor.js, audio.js, touch-bridge.js, keyboard.js)
├── tracking/
│   └── hand_mouse/           (hand-tracking + kalibratie, MediaPipe-modellen)
│       ├── hand_mouse.multicolor_2026-06-16.py   ← de tracker (cursor + pinch-klik)
│       ├── calibrate_*.py / *_test.py            (kalibratie- en diagnose-scripts)
│       ├── calibration.json                      (voorbeeld-kalibratie)
│       └── *.task                                (MediaPipe-modellen, meegeleverd)
└── motor/                    (bridge.py + ESP32-firmware in receiver_esp32/)
```

---

## Benodigdheden

**Hardware**
- MacBook + beamer als 2e scherm.
- DJI Action 5 Pro in webcam-modus (top-view, schuin van boven).
- Wit bord als projectievlak.
- Voor de trilling: 2× ESP32 (zender + ontvanger), L298N-motordriver, DC-trilmotor,
  expansionboard met eigen voeding, en een **data**-USB-C-kabel voor de zender.

**Software**
- macOS met **Camera-permissie** voor je Terminal
  (Systeeminstellingen → Privacy en beveiliging → Camera).
- Python 3.12.

---

## Installatie

```bash
git clone <repo-url> hyperbridge
cd hyperbridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

De MediaPipe-modellen (`gesture_recognizer.task`, `hand_landmarker.task`) zitten al in
`tracking/hand_mouse/`, dus je hoeft niets te downloaden.

---

## Opstarten (3 stappen)

Open per stap een eigen Terminal-venster (met de venv actief: `source .venv/bin/activate`).

### 1. Website (local)
```bash
cd website && python3 -m http.server 8008
```
Open daarna `http://localhost:8008/map-app.html` (volledig scherm op de beamer).

### 2. Handtracking (cursor + klik)
```bash
cd tracking/hand_mouse && python hand_mouse.multicolor_2026-06-16.py
```
- Kiest automatisch de camera en de beamer; lukt dat niet: `--camera 0 --display 2`.
- **Kalibreren:** druk in het preview-venster op **`a`** en klik de **4 schermhoeken**
  aan (linksboven → rechtsboven → rechtsonder → linksonder). Het script meet daarna met
  gekleurde stippen het hele scherm in. Hoeken bijslepen kan met de muis; grid fijner/
  grover met **`+` / `-`**.
- **Bedienen:** wijs om de cursor te sturen, **pinch (👌)** of een **vuist** = klik. De
  klik wordt op het klikpunt vastgezet (geen ongewenst slepen); bewust ver bewegen tijdens
  een pinch = slepen.

### 3. Bridge (trilmotor)
```bash
cd motor && python bridge.py
```
- Detecteert de ESP32-zender automatisch en draait op poort **5001**.
- Voertuig kiezen in de maps-app → geluid + trilling. De trilsterkte per voertuig staat in
  `website/src/motor.js` (`MODE_PWM`); aanpassen + in de browser hard refreshen (Cmd+Shift+R).
- De ESP32-firmware staat in `motor/receiver_esp32/`.

---

## Let op: grote mediabestanden

`website/Links/` bevat de audio en video van de installatie (~210 MB; de grootste is
`Plane.mp3`, 89 MB). Dat past binnen GitHub's limiet van 100 MB per bestand, maar maakt de
repo zwaar. Overweeg **Git LFS** voor de media:

```bash
git lfs install
git lfs track "*.mp3" "*.mp4" "*.wav"
git add .gitattributes
```

Of verwijder de map `website/Links/` als de media niet mee hoeven naar GitHub.

---

## Credits

Afstudeerproject. De ESP32-trilmotor-firmware is gebaseerd op werk van Merijn
(`motor/receiver_esp32/`). Hand-tracking met Google MediaPipe.
