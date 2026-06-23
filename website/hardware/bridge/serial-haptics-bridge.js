#!/usr/bin/env node
/**
 * Local WebSocket -> Serial bridge for haptics.
 * Receives JSON payloads from the webapp and writes compact commands to Arduino.
 *
 * Usage:
 *   npm i ws serialport
 *   node serial-haptics-bridge.js --port /dev/tty.usbmodem1101 --baud 115200 --ws 8765
 */

import { WebSocketServer } from "ws";
import { SerialPort } from "serialport";

const args = parseArgs(process.argv.slice(2));
const serialPath = args.port || "/dev/tty.usbmodem1101";
const baudRate = Number(args.baud || 115200);
const wsPort = Number(args.ws || 8765);

const serial = new SerialPort({
  path: serialPath,
  baudRate,
});

const wss = new WebSocketServer({ port: wsPort });

serial.on("open", () => {
  console.log(`[bridge] serial connected ${serialPath} @ ${baudRate}`);
});

serial.on("error", (err) => {
  console.error("[bridge] serial error:", err.message);
});

wss.on("listening", () => {
  console.log(`[bridge] websocket listening on ws://localhost:${wsPort}`);
});

wss.on("connection", (socket) => {
  console.log("[bridge] client connected");
  socket.on("message", (message) => {
    try {
      const data = JSON.parse(message.toString());
      const command = toArduinoCommand(data);
      serial.write(`${command}\n`);
    } catch (err) {
      console.error("[bridge] invalid payload:", err.message);
    }
  });
});

function toArduinoCommand(data) {
  const levelMap = { low: 60, medium: 130, high: 220 };
  const level = levelMap[data.level] || 100;
  const pattern = Array.isArray(data.pattern) ? data.pattern.join(",") : `${level}`;
  return `PULSE:${level}:${pattern}`;
}

function parseArgs(values) {
  const parsed = {};
  for (let i = 0; i < values.length; i += 2) {
    const key = values[i]?.replace(/^--/, "");
    const value = values[i + 1];
    if (key) parsed[key] = value;
  }
  return parsed;
}
