// Trilmotor-ONTVANGER (ESP32 #2 — zit aan de motor / op stroom).
// ESP-NOW receiver + L298N DC-motordriver.
//
// SLIMME versie: accepteert nu naast de vaste standen óók een VRIJE PWM-waarde,
// zodat je het trilgevoel volledig vanuit software (de website) kunt regelen —
// geen herflashen meer nodig om iets bij te stellen.
//
// Commando's die deze ontvanger begrijpt (komen via de zender binnen):
//   "0" t/m "255"  -> zet de motor direct op die PWM-duty (0 = uit)
//   "SPEED1..4"    -> vaste standen (afgesteld via nulmeting, zie hieronder)
//   "OFF"          -> motor uit
//
// Flashen: open in Arduino IDE, board = je ESP32, selecteer de poort van DEZE
// (de ontvanger; sluit 'm dus even via USB op de computer aan), Upload.

#include <WiFi.h>
#include <esp_now.h>

const int ENA = 25;   // PWM-pin (snelheid)
const int IN1 = 26;   // richting
const int IN2 = 27;   // richting

// Vaste standen (0-255) — alleen nog als fallback; het echte afstellen gebeurt
// nu vanuit de website met vrije PWM-waarden.
const int PWM_SPEED1 = 26;   // ~10%  -> hyperloop
const int PWM_SPEED2 = 77;   // ~30%  -> vliegtuig
const int PWM_SPEED3 = 140;  // ~55%  -> trein
const int PWM_SPEED4 = 168;  // ~66%  -> benzine auto

char cmd[20];
bool newData = false;

void setMotorSpeed(int speed) {
  if (speed < 0) speed = 0;
  if (speed > 255) speed = 255;
  analogWrite(ENA, speed);
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  Serial.print("SPEED SET TO: ");
  Serial.println(speed);
}

void stopMotor() {
  analogWrite(ENA, 0);
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  Serial.println("MOTOR OFF");
}

bool isAllDigits(const String &s) {
  if (s.length() == 0) return false;
  for (unsigned int i = 0; i < s.length(); i++) {
    if (!isDigit(s[i])) return false;
  }
  return true;
}

void OnDataRecv(const esp_now_recv_info *info,
                const uint8_t *data,
                int len) {
  if (len >= (int)sizeof(cmd)) len = sizeof(cmd) - 1;
  memset(cmd, 0, sizeof(cmd));
  memcpy(cmd, data, len);
  cmd[len] = '\0';
  Serial.print("CMD: ");
  Serial.println(cmd);
  newData = true;
}

void setup() {
  Serial.begin(115200);

  pinMode(ENA, OUTPUT);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);

  WiFi.mode(WIFI_STA);

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW ERROR");
    return;
  }

  esp_now_register_recv_cb(OnDataRecv);
  Serial.println("RECEIVER READY");
}

void loop() {
  if (!newData) return;

  String c = String(cmd);
  c.trim();

  if (c == "OFF") {
    stopMotor();
  }
  else if (isAllDigits(c)) {        // vrije PWM-waarde 0-255 (0 = uit)
    int pwm = c.toInt();
    if (pwm <= 0) stopMotor();
    else setMotorSpeed(pwm);
  }
  else if (c == "SPEED1") setMotorSpeed(PWM_SPEED1);
  else if (c == "SPEED2") setMotorSpeed(PWM_SPEED2);
  else if (c == "SPEED3") setMotorSpeed(PWM_SPEED3);
  else if (c == "SPEED4") setMotorSpeed(PWM_SPEED4);

  newData = false;
}
