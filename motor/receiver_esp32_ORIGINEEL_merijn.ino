// BACKUP — Merijn's ORIGINELE receiver-firmware (wat er op de motor-ESP32 stond
// vóór het afstellen). Bewaard als herstelpunt: flash dit terug om exact het
// oude gedrag te krijgen (vaste standen 64/128/192/255, geen vrije PWM).
//
// Gemaakt: 16-06-2026, vlak voor het uploaden van de afgestelde/slimme versie
// (receiver_esp32.ino).

#include <WiFi.h>
#include <esp_now.h>

const int ENA = 25;
const int IN1 = 26;
const int IN2 = 27;

char cmd[20];
bool newData = false;

void setMotorSpeed(int speed) {

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

void OnDataRecv(const esp_now_recv_info *info,
                const uint8_t *data,
                int len) {

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

  if (c == "SPEED1") {
    setMotorSpeed(64);
  }

  else if (c == "SPEED2") {
    setMotorSpeed(128);
  }

  else if (c == "SPEED3") {
    setMotorSpeed(192);
  }

  else if (c == "SPEED4") {
    setMotorSpeed(255);
  }

  else if (c == "OFF") {
    stopMotor();
  }

  newData = false;
}
