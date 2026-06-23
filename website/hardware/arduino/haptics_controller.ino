/*
  Minimal haptics controller for impact table.
  Expected serial command format:
    PULSE:<intensity>:<pattern_csv>
  Example:
    PULSE:130:130,80,130
*/

const int motorPin = 9;
String buffer = "";

void setup() {
  pinMode(motorPin, OUTPUT);
  analogWrite(motorPin, 0);
  Serial.begin(115200);
}

void loop() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      handleCommand(buffer);
      buffer = "";
    } else {
      buffer += c;
    }
  }
}

void handleCommand(String line) {
  line.trim();
  if (!line.startsWith("PULSE:")) {
    return;
  }

  int firstColon = line.indexOf(':');
  int secondColon = line.indexOf(':', firstColon + 1);
  if (firstColon < 0 || secondColon < 0) return;

  int intensity = line.substring(firstColon + 1, secondColon).toInt();
  String pattern = line.substring(secondColon + 1);

  playPattern(constrain(intensity, 0, 255), pattern);
}

void playPattern(int intensity, String pattern) {
  int start = 0;
  bool motorOn = true;

  while (true) {
    int comma = pattern.indexOf(',', start);
    String token = comma == -1 ? pattern.substring(start) : pattern.substring(start, comma);
    token.trim();
    int durationMs = token.toInt();
    if (durationMs > 0) {
      analogWrite(motorPin, motorOn ? intensity : 0);
      delay(durationMs);
      motorOn = !motorOn;
    }

    if (comma == -1) break;
    start = comma + 1;
  }

  analogWrite(motorPin, 0);
}
