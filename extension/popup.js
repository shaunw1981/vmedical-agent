"use strict";

// --- tiny helpers ------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const show = (el, on = true) => { el.hidden = !on; };
let CFG = { url: "", key: "", email: "" };
let MODE = "existing"; // or "new"

function views(active) {
  ["view-login", "view-main", "view-done"].forEach((v) => show($(v), v === active));
  show($("logout"), active !== "view-login");
}

function setMsg(el, text, kind) {
  el.textContent = text || "";
  el.className = "msg" + (kind ? " " + kind : "");
}

async function api(path, opts = {}) {
  const headers = Object.assign(
    { "X-API-Key": CFG.key, "Content-Type": "application/json" },
    opts.headers || {}
  );
  const res = await fetch(CFG.url + path, Object.assign({}, opts, { headers }));
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (res.status === 401) {
    const err = new Error("unauthorized"); err.unauthorized = true; throw err;
  }
  return { ok: res.ok, status: res.status, data };
}

// --- storage -----------------------------------------------------------------
function loadConfig() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["url", "key", "email"], (v) => resolve(v || {}));
  });
}
function saveConfig(cfg) {
  return new Promise((resolve) => chrome.storage.local.set(cfg, resolve));
}
function clearConfig() {
  return new Promise((resolve) => chrome.storage.local.remove(["url", "key", "email"], resolve));
}

// --- login -------------------------------------------------------------------
async function doLogin() {
  const url = $("cfg-url").value.trim().replace(/\/+$/, "");
  const key = $("cfg-key").value.trim();
  const email = $("cfg-email").value.trim();
  if (!url || !key) { setMsg($("login-msg"), "Enter the dashboard address and access key.", "err"); return; }
  CFG = { url, key, email };
  setMsg($("login-msg"), "Checking…", "");
  try {
    const r = await api("/api/appointment-types");
    if (!r.ok) throw new Error("bad");
    await saveConfig(CFG);
    populateTypes(r.data.types || []);
    startMain();
  } catch (e) {
    if (e.unauthorized) setMsg($("login-msg"), "That access key was rejected.", "err");
    else setMsg($("login-msg"), "Couldn't reach the dashboard. Check the address.", "err");
  }
}

async function doLogout() {
  await clearConfig();
  CFG = { url: "", key: "", email: "" };
  $("cfg-key").value = "";
  views("view-login");
}

// --- appointment types -------------------------------------------------------
function populateTypes(types) {
  const sel = $("f-type");
  sel.innerHTML = '<option value="" disabled selected>Choose one…</option>';
  types.forEach((t) => {
    const o = document.createElement("option");
    o.value = t.key; o.textContent = t.label;
    sel.appendChild(o);
  });
}

async function ensureTypes() {
  if ($("f-type").options.length > 1) return;
  try {
    const r = await api("/api/appointment-types");
    if (r.ok) populateTypes(r.data.types || []);
  } catch (e) { /* handled elsewhere */ }
}

// --- search ------------------------------------------------------------------
let searchTimer = null;
function onSearchInput() {
  const q = $("search").value.trim();
  clearTimeout(searchTimer);
  const box = $("results");
  if (q.length < 2) { box.innerHTML = ""; return; }
  box.innerHTML = '<div class="res-empty">Searching…</div>';
  searchTimer = setTimeout(async () => {
    try {
      const r = await api("/api/contacts/search?q=" + encodeURIComponent(q));
      renderResults(r.data && r.data.contacts ? r.data.contacts : []);
    } catch (e) {
      if (e.unauthorized) return doLogout();
      box.innerHTML = '<div class="res-empty">Search failed.</div>';
    }
  }, 250);
}

function renderResults(rows) {
  const box = $("results");
  box.innerHTML = "";
  if (!rows.length) {
    box.innerHTML = '<div class="res-empty">No matches found.</div>';
    return;
  }
  rows.forEach((c) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "res";
    const n = document.createElement("div"); n.className = "rn";
    n.textContent = c.name || "(no name)";
    const s = document.createElement("div"); s.className = "rs";
    s.textContent = [c.phone, c.email].filter(Boolean).join(" · ");
    b.appendChild(n); b.appendChild(s);
    b.addEventListener("click", () => selectContact(c));
    box.appendChild(b);
  });
}

function splitName(name) {
  const parts = (name || "").trim().split(/\s+/);
  return { first: parts.shift() || "", last: parts.join(" ") };
}

function selectContact(c) {
  MODE = "existing";
  const nm = splitName(c.name);
  $("f-first").value = nm.first;
  $("f-last").value = nm.last;
  $("f-email").value = c.email || "";
  $("f-phone").value = c.phone || "";
  openForm("Existing client", false);
}

function addNew() {
  MODE = "new";
  ["f-first", "f-last", "f-email", "f-phone"].forEach((id) => ($(id).value = ""));
  // Seed a name from whatever they typed in search, if it looks like a name.
  const q = $("search").value.trim();
  if (q && !/[@\d]/.test(q)) { const nm = splitName(q); $("f-first").value = nm.first; $("f-last").value = nm.last; }
  openForm("New client", true);
  $("f-first").focus();
}

function openForm(pillText, isNew) {
  const pill = $("mode-pill");
  pill.textContent = pillText;
  pill.className = "pill" + (isNew ? " new" : "");
  $("results").innerHTML = "";
  show($("form"), true);
  setMsg($("main-msg"), "", "");
}

function resetForm() {
  show($("form"), false);
  ["f-first", "f-last", "f-email", "f-phone", "f-when"].forEach((id) => ($(id).value = ""));
  $("f-type").selectedIndex = 0;
  $("search").value = "";
  $("results").innerHTML = "";
  setMsg($("main-msg"), "", "");
  $("search").focus();
}

// --- schedule ----------------------------------------------------------------
async function schedule() {
  const first = $("f-first").value.trim();
  const last = $("f-last").value.trim();
  const name = (first + " " + last).trim();
  const email = $("f-email").value.trim();
  const phone = $("f-phone").value.trim();
  const type_key = $("f-type").value;
  const appt_at = $("f-when").value;

  if (!name) return setMsg($("main-msg"), "Enter the client's name.", "err");
  if (!email && !phone) return setMsg($("main-msg"), "Enter an email or phone number.", "err");
  if (!type_key) return setMsg($("main-msg"), "Choose an appointment type.", "err");
  if (!appt_at) return setMsg($("main-msg"), "Choose the appointment date and time.", "err");

  setMsg($("main-msg"), "Scheduling…", "");
  $("schedule").disabled = true;
  try {
    const r = await api("/api/reminders", {
      method: "POST",
      body: JSON.stringify({ contact_name: name, email, phone, type_key, appt_at, staff: CFG.email }),
    });
    if (r.ok && r.data && r.data.ok) {
      const label = r.data.label || "the appointment";
      let msg = "Reminder scheduled for " + name + " — added to the " + label + " follow-up";
      msg += r.data.booked ? " and booked on the calendar." : ".";
      if (r.data.warning) msg += " Note: " + r.data.warning;
      $("done-msg").textContent = msg;
      views("view-done");
    } else {
      const err = (r.data && r.data.error) ? r.data.error : "Couldn't schedule the reminder.";
      setMsg($("main-msg"), err, "err");
    }
  } catch (e) {
    if (e.unauthorized) return doLogout();
    setMsg($("main-msg"), "Network error — please try again.", "err");
  } finally {
    $("schedule").disabled = false;
  }
}

function startMain() {
  views("view-main");
  resetForm();
  show($("add-new"), true);
}

// --- boot --------------------------------------------------------------------
async function boot() {
  const c = await loadConfig();
  if (c && c.url && c.key) {
    CFG = { url: c.url, key: c.key, email: c.email || "" };
    // Prefill login form too, in case the key later fails.
    $("cfg-url").value = c.url; $("cfg-email").value = c.email || "";
    try {
      const r = await api("/api/appointment-types");
      if (r.ok) { populateTypes(r.data.types || []); startMain(); }
      else throw new Error("bad");
    } catch (e) {
      views("view-login");
      setMsg($("login-msg"), e.unauthorized ? "Your saved key was rejected — sign in again." : "", "err");
    }
  } else {
    views("view-login");
  }

  $("login-btn").addEventListener("click", doLogin);
  $("logout").addEventListener("click", doLogout);
  $("search").addEventListener("input", onSearchInput);
  $("add-new").addEventListener("click", addNew);
  $("reset").addEventListener("click", resetForm);
  $("schedule").addEventListener("click", schedule);
  $("again").addEventListener("click", startMain);
}

document.addEventListener("DOMContentLoaded", boot);
