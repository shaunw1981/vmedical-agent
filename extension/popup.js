"use strict";

// ---- settings --------------------------------------------------------------
function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["baseUrl", "apiKey", "staff"], (s) => resolve(s || {}));
  });
}

let CFG = { baseUrl: "", apiKey: "", staff: "" };

function api(path, opts = {}) {
  const headers = Object.assign({ "X-API-Key": CFG.apiKey }, opts.headers || {});
  if (opts.body) headers["Content-Type"] = "application/json";
  return fetch(CFG.baseUrl.replace(/\/+$/, "") + path, { ...opts, headers });
}

// ---- elements --------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const els = {};

function banner(msg, kind) {
  const b = $("banner");
  b.textContent = msg;
  b.className = "banner " + (kind || "");
  b.hidden = !msg;
}

// ---- patient search --------------------------------------------------------
let searchTimer = null;
let selectedPatientId = "";

function wireSearch() {
  const box = $("patientSearch");
  const results = $("results");
  box.addEventListener("input", () => {
    selectedPatientId = "";
    $("selected").textContent = "";
    clearTimeout(searchTimer);
    const q = box.value.trim();
    if (q.length < 2) { results.hidden = true; return; }
    searchTimer = setTimeout(async () => {
      try {
        const r = await api("/api/patients/search?q=" + encodeURIComponent(q));
        const d = await r.json();
        results.innerHTML = "";
        (d.patients || []).forEach((p) => {
          const el = document.createElement("div");
          el.className = "ac-item";
          el.innerHTML = '<div>' + escapeHtml(p.label) + '</div><div class="ac-sub">' +
            escapeHtml((p.email || "") + (p.phone ? " · " + p.phone : "")) + '</div>';
          el.addEventListener("click", () => {
            selectedPatientId = p.id;
            box.value = p.label;
            $("email").value = p.email || "";
            $("phone").value = p.phone || "";
            $("selected").textContent = "✓ Using patient record #" + p.id;
            results.hidden = true;
            $("newPatient").hidden = true;
            loadContent(false);
          });
          results.appendChild(el);
        });
        results.hidden = (d.patients || []).length === 0;
      } catch (e) { results.hidden = true; }
    }, 200);
  });
  document.addEventListener("click", (e) => {
    if (!box.contains(e.target) && !results.contains(e.target)) results.hidden = true;
  });
}

// ---- add patient -----------------------------------------------------------
function wireAddPatient() {
  $("addPatientLink").addEventListener("click", (e) => {
    e.preventDefault();
    const np = $("newPatient");
    np.hidden = !np.hidden;
    if (!np.hidden) { selectedPatientId = ""; $("npFirst").focus(); }
  });
  $("createPatient").addEventListener("click", async () => {
    const first = $("npFirst").value.trim();
    const last = $("npLast").value.trim();
    if (!first && !last) { banner("Enter at least a first or last name.", "err"); return; }
    try {
      const r = await api("/api/patients", {
        method: "POST",
        body: JSON.stringify({
          first_name: first, last_name: last,
          email: $("npEmail").value.trim(), phone: $("npPhone").value.trim(),
        }),
      });
      const d = await r.json();
      if (!r.ok) { banner(d.error || "Could not create the patient.", "err"); return; }
      const p = d.patient;
      selectedPatientId = p.id;
      $("patientSearch").value = ((p.first_name || "") + " " + (p.last_name || "")).trim();
      $("email").value = p.email || $("npEmail").value.trim();
      $("phone").value = p.phone || $("npPhone").value.trim();
      $("selected").textContent = "✓ New patient record #" + p.id + " created";
      $("newPatient").hidden = true;
      banner("", "");
      loadContent(false);
    } catch (e) { banner("Network error creating the patient.", "err"); }
  });
}

// ---- editable content from the per-service template ------------------------
const contentFields = ["emailSubject", "emailBody", "smsText", "reviewDays", "reviewBody"];
let autofill = {};

function dirty(id) { return $(id).value !== (autofill[id] || ""); }

async function loadContent(force) {
  const type = $("typeKey").value;
  if (!type) return;
  const qs = "type_key=" + encodeURIComponent(type) +
    "&name=" + encodeURIComponent($("patientSearch").value) +
    "&appt_at=" + encodeURIComponent($("apptAt").value || "");
  try {
    const r = await api("/api/reminder-content?" + qs);
    const c = await r.json();
    const set = (id, val) => { if (force || !dirty(id)) { $(id).value = val; autofill[id] = String(val); } };
    set("emailSubject", c.email_subject || "");
    set("emailBody", c.email_body || "");
    set("smsText", c.sms_text || "");
    if (force || $("leadDays").value === "3" || $("leadDays").value === "") $("leadDays").value = c.lead_days;
    set("reviewDays", String(c.review_days || 0));
    set("reviewBody", c.review_body || "");
    $("contentBox").open = true;
  } catch (e) { /* leave fields as-is */ }
}

// ---- schedule --------------------------------------------------------------
function wireSchedule() {
  $("scheduleBtn").addEventListener("click", async () => {
    const payload = {
      patient_id: selectedPatientId || null,
      contact_name: $("patientSearch").value.trim(),
      email: $("email").value.trim(),
      phone: $("phone").value.trim(),
      type_key: $("typeKey").value,
      appt_at: $("apptAt").value,
      lead_days: parseInt($("leadDays").value || "3", 10),
      email_subject: $("emailSubject").value,
      email_body: $("emailBody").value,
      sms_text: $("smsText").value,
      review_days: parseInt($("reviewDays").value || "0", 10),
      review_body: $("reviewBody").value,
      staff: CFG.staff || "",
    };
    if (!payload.contact_name) { banner("Choose or add a patient first.", "err"); return; }
    if (!payload.type_key) { banner("Pick a service.", "err"); return; }
    if (!payload.appt_at) { banner("Set the appointment date and time.", "err"); return; }
    if (!payload.email && !payload.phone) { banner("Add an email or a mobile number.", "err"); return; }

    const btn = $("scheduleBtn");
    btn.disabled = true; btn.textContent = "Scheduling…";
    try {
      const r = await api("/api/reminders", { method: "POST", body: JSON.stringify(payload) });
      const d = await r.json();
      if (!r.ok || !d.ok) { banner(d.error || "Could not schedule the reminder.", "err"); return; }
      const ch = d.channels || {};
      const via = [ch.email ? "email" : null, ch.sms ? "text" : null].filter(Boolean).join(" + ") || "no channel";
      let msg = "✓ Reminder set for " + (d.label || "appointment") +
        " — sends " + fmtWhen(d.reminder_due_at) + " (" + via + ").";
      if (d.warning) msg += " Note: " + d.warning;
      banner(msg, "ok");
      resetForm();
    } catch (e) {
      banner("Network error — is the dashboard reachable?", "err");
    } finally {
      btn.disabled = false; btn.textContent = "Schedule reminder";
    }
  });
  $("resetTpl").addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); loadContent(true); });
  $("typeKey").addEventListener("change", () => loadContent(true));
  $("apptAt").addEventListener("change", () => loadContent(false));
}

function resetForm() {
  selectedPatientId = "";
  ["patientSearch", "email", "phone", "apptAt", "emailSubject", "emailBody", "smsText", "reviewBody"].forEach((id) => $(id).value = "");
  $("typeKey").selectedIndex = 0;
  $("leadDays").value = "3"; $("reviewDays").value = "0";
  $("selected").textContent = "";
  autofill = {};
}

// ---- appointment types -----------------------------------------------------
async function loadTypes() {
  const sel = $("typeKey");
  try {
    const r = await api("/api/appointment-types");
    const d = await r.json();
    (d.types || []).forEach((t) => {
      const o = document.createElement("option");
      o.value = t.key; o.textContent = t.label;
      sel.appendChild(o);
    });
    return true;
  } catch (e) { return false; }
}

// ---- helpers ---------------------------------------------------------------
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtWhen(iso) {
  if (!iso) return "soon";
  try {
    const d = new Date(iso.length <= 16 ? iso : iso);
    if (isNaN(d)) return iso.slice(0, 16).replace("T", " ");
    return d.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  } catch (e) { return iso; }
}

function defaultApptAt() {
  // default to tomorrow 9:00am local, in datetime-local format
  const d = new Date();
  d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0);
  const p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + "T" + p(d.getHours()) + ":" + p(d.getMinutes());
}

// ---- boot ------------------------------------------------------------------
async function boot() {
  $("gearBtn").addEventListener("click", () => chrome.runtime.openOptionsPage());
  $("openSetup").addEventListener("click", () => chrome.runtime.openOptionsPage());

  CFG = Object.assign(CFG, await getSettings());
  if (!CFG.baseUrl || !CFG.apiKey) {
    $("setupNeeded").hidden = false;
    return;
  }
  $("main").hidden = false;
  $("apptAt").value = defaultApptAt();
  wireSearch(); wireAddPatient(); wireSchedule();
  const ok = await loadTypes();
  if (!ok) {
    banner("Couldn't reach the dashboard. Check the address and API key in settings, and that this device can open it.", "err");
  }
}

document.addEventListener("DOMContentLoaded", boot);
