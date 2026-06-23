#!/usr/bin/env node
/**
 * Controle: zichtbare copy in HTML (p, h1–h4, chart-captions) en TIMELINE ≤200 tekens.
 * Run: node scripts/check-ui-copy-length.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, "..");
const MAX = 200;

function stripTags(html) {
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function checkBlock(file, label, raw) {
  const t = stripTags(raw);
  if (t.length > MAX) console.log(`${file} :: ${label} (${t.length}): ${t.slice(0, 140)}…`);
}

const files = [
  "index.html",
  "welkom.html",
  "hyperloop.html",
  "veiligheid.html",
  "gevolgen.html",
  "regio.html",
  "je-stem.html",
  "map-app.html",
];

for (const name of files) {
  const fp = path.join(root, name);
  let html = fs.readFileSync(fp, "utf8");
  html = html.replace(/<script[\s\S]*?<\/script>/gi, "").replace(/<style[\s\S]*?<\/style>/gi, "");

  const re = /<(p|h1|h2|h3|h4)(\b[^>]*)>([\s\S]*?)<\/\1>/gi;
  let m;
  let i = 0;
  while ((m = re.exec(html))) {
    checkBlock(name, `${m[1]}#${i++}`, m[3]);
  }

  const ph = /placeholder="([^"]+)"/g;
  while ((m = ph.exec(html))) checkBlock(name, "placeholder", m[1]);

  const aria = /aria-label="([^"]{30,})"/g;
  while ((m = aria.exec(html))) checkBlock(name, "aria-label", m[1]);
}

const hyp = fs.readFileSync(path.join(root, "hyperloop.html"), "utf8");
const block = hyp.match(/const TIMELINE = (\[[\s\S]*?\]);/);
if (block) {
  const arr = new Function(`return ${block[1]}`)();
  arr.forEach((item, i) => {
    checkBlock("hyperloop.html", `TIMELINE[${i}].short`, item.short);
    checkBlock("hyperloop.html", `TIMELINE[${i}].text`, item.text);
  });
}

console.log("Check klaar (geen regels hierboven = OK voor p/h1–h4/placeholders/TIMELINE).");
