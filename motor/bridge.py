from flask import Flask
import serial
from serial.tools import list_ports

app = Flask(__name__)

# Sta verzoeken vanaf de maps-site (andere poort/origin) toe — anders blokkeert
# de browser de fetch naar deze bridge met een CORS-fout.
@app.after_request
def add_cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

def find_esp32():

    ports = list_ports.comports()

    for port in ports:

        print("Gevonden:", port.device, "-", port.description)

        desc = port.description.lower()

        if (
            "usb" in desc
            or "cp210" in desc
            or "ch340" in desc
            or "silicon labs" in desc
            or "esp32" in desc
        ):
            return port.device

    return None


port = find_esp32()

if port is None:
    raise Exception("Geen ESP32 gevonden")

print(f"ESP32 gevonden op {port}")

ser = serial.Serial(port, 115200)

@app.route('/api/<cmd>')
def send(cmd):

    cmd = cmd.upper()

    ser.write((cmd + '\n').encode())

    print("VERSTUURD:", cmd)

    return "OK"

@app.route('/')
def home():

    return "ESP32 Bridge Online"

# Poort 5000 is op macOS bezet door AirPlay Receiver → daarom 5001.
app.run(
    host='0.0.0.0',
    port=5001
)
