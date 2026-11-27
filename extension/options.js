"use strict";

const $ = (id) => document.getElementById(id);

function banner(msg, kind) {
  const b = $("banner");
  b.textContent = msg;
  b.className = "banner " + (kind || "");
  b.hidden = !msg;
}

function normalizeBase(v) {
  v = (v || "").trim().replace(/\/+$/, "");
  if (v && !/^https?:\/\//i.test(v)) v = "http://" + v;
  return v;
}

// Turn a base URL into an origin match pattern for host permissions.
function originPattern(base) {
  try {
    const u = new URL(base);
    return u.protocol + "//" + u.hostname + (u.port ? ":" + u.port : "") + "/*";
  } catch (e) { return null; }
}

function requestHostPermission(base) {
  const pattern = originPattern(base);
  if (!pattern) return Promise.resolve(false);
  return new Promise((resolve) => {
    chrome.permissions.request({ origins: [pattern] }, (granted) => resolve(!!granted));
  });
}

function load() {
  chrome.storage.sync.get(["baseUrl", "apiKey", "staff"], (s) => {
    $("baseUrl").value = s.baseUrl || "";
    $("apiKey").value = s.apiKey || "";
    $("staff").value = s.staff || "";
  });
}

async function testConnection(base, key) {
  try {
    const r = await fetch(base.replace(/\/+$/, "") + "/api/appointment-types", {
      headers: { "X-API-Key": key },
    });
    if (r.status === 401) return { ok: false, msg: "Connected, but the API key was rejected (401)." };
    if (!r.ok) return { ok: false, msg: "Dashboard responded with status " + r.status + "." };
    const d = await r.json();
    const n = (d.types || []).length;
    return { ok: true, msg: "✓ Connected — " + n + " service type" + (n === 1 ? "" : "s") + " loaded." };
  } catch (e) {
    return { ok: false, msg: "Couldn't reach the dashboard. Check the address and that this device can open it." };
  }
}

async function save() {
  const base = normalizeBase($("baseUrl").value);
  const key = $("apiKey").value.trim();
  const staff = $("staff").value.trim();
  if (!base) { banner("Enter the dashboard address.", "err"); return; }
  if (!key) { banner("Enter the API key.", "err"); return; }
  $("baseUrl").value = base;

  const granted = await requestHostPermission(base);
  if (!granted) {
    banner("Chrome needs permission to reach " + base + ". Click Save again and allow it.", "err");
    return;
  }
  const test = await testConnection(base, key);
  chrome.storage.sync.set({ baseUrl: base, apiKey: key, staff: staff }, () => {
    banner((test.ok ? "Saved. " : "Saved, but ") + test.msg, test.ok ? "ok" : "err");
  });
}

async function test() {
  const base = normalizeBase($("baseUrl").value);
  const key = $("apiKey").value.trim();
  if (!base || !key) { banner("Enter the address and API key first.", "err"); return; }
  const granted = await requestHostPermission(base);
  if (!granted) { banner("Permission to reach " + base + " was not granted.", "err"); return; }
  banner("Testing…", "");
  const t = await testConnection(base, key);
  banner(t.msg, t.ok ? "ok" : "err");
}

document.addEventListener("DOMContentLoaded", () => {
  load();
  $("saveBtn").addEventListener("click", save);
  $("testBtn").addEventListener("click", test);
});
