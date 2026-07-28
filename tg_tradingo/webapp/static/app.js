"use strict";

const $ = (id) => document.getElementById(id);

function dot(status) {
  const cls = ["ok", "warn", "crit", "off"].includes(status) ? status : "off";
  return `<span class="dot ${cls}"></span>`;
}

function fmtTs(ts) {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d)) return ts;
  return d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function renderLights(lights) {
  const order = ["bridge", "mt5_local", "friend_link", "friend_heartbeat"];
  const html = order
    .filter((k) => lights[k])
    .map((k) => {
      const l = lights[k];
      return `<div class="card light">
        ${dot(l.status)}
        <div>
          <div class="label">${esc(l.label || k)}</div>
          <div class="detail">${esc(l.detail || "")}</div>
        </div>
      </div>`;
    })
    .join("");
  $("lights").innerHTML = html || '<div class="card">Nessun check configurato</div>';
}

function renderChannels(channels) {
  const html = (channels || [])
    .map((ch) => {
      const t = ch.today || {};
      const last = ch.last_emitted || ch.last_event;
      const lastHtml = last
        ? `<div class="lastmsg">
             ${fmtTs(last.ts_utc)} —
             ${last.action ? `<span class="action">${esc(last.action)}</span> · ` : ""}
             ${esc(last.outcome || "")}<br>${esc(last.raw_text || "")}
           </div>`
        : `<div class="lastmsg">Nessun evento oggi</div>`;
      return `<div class="card channel-card">
        <div class="head">
          <span class="name ${ch.enabled ? "" : "disabled"}">${esc(ch.name)}</span>
          <span class="badge">${esc(ch.id)}</span>
        </div>
        <div class="counts">
          <span class="em">Segnali <b>${t.emitted ?? 0}</b></span>
          <span>Ignorati <b>${(t.ignored ?? 0) + (t.duplicates ?? 0)}</b></span>
          <span>Non capiti <b>${t.unparsed ?? 0}</b></span>
          <span class="er">Errori <b>${t.errors ?? 0}</b></span>
        </div>
        ${lastHtml}
      </div>`;
    })
    .join("");
  $("channels").innerHTML = html || '<div class="card">Nessun canale configurato</div>';
}

function renderEvents(events) {
  const html = (events || [])
    .map(
      (e) => `<tr>
        <td class="ts">${fmtTs(e.ts_utc)}</td>
        <td class="ch">${esc((e.channel_id || "").replace("CH_", ""))}</td>
        <td class="outcome-${esc(e.outcome || "")}">${esc(e.outcome || "")}${e.action ? " · " + esc(e.action) : ""}</td>
        <td class="raw">${esc(e.raw_text || "")}</td>
      </tr>`
    )
    .join("");
  $("events").innerHTML = html || '<tr><td class="raw">Nessun evento oggi</td></tr>';
}

async function refresh() {
  try {
    const res = await fetch("/api/status", { cache: "no-store" });
    if (res.status === 401) {
      location.href = "/login";
      return;
    }
    const data = await res.json();
    $("overall").className = `overall-dot dot ${data.overall || "off"}`;
    $("updated").textContent = "agg. " + fmtTs(data.generated_utc);
    renderLights(data.lights || {});
    renderChannels(data.channels || []);
    renderEvents(data.events || []);
  } catch (err) {
    $("updated").textContent = "offline?";
    $("overall").className = "overall-dot dot crit";
  }
}

refresh();
setInterval(refresh, 15000);
