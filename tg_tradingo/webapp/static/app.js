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

function fmtMoney(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const v = Number(n);
  const sign = v > 0 ? "+" : "";
  return sign + v.toFixed(2);
}

function pnlClass(n) {
  if (n > 0) return "pos";
  if (n < 0) return "neg";
  return "";
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

function sparkline(points) {
  if (!points || points.length < 2) return "";
  const vals = points.map((p) => p.equity);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const w = 320;
  const h = 72;
  const pad = 4;
  const coords = points
    .map((p, i) => {
      const x = pad + (i / (points.length - 1)) * (w - 2 * pad);
      const y = h - pad - ((p.equity - min) / span) * (h - 2 * pad);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const stroke = vals[vals.length - 1] >= vals[0] ? "#d4af37" : "#ef4444";
  return `<polyline fill="none" stroke="${stroke}" stroke-width="2" points="${coords}" />`;
}

function accountCard(acc) {
  const equity = acc.equity || {};
  const latest = equity.latest || null;
  const delta = equity.delta_today;
  const totals = (acc.pnl && acc.pnl.totals) || {};
  const windows = [
    { key: "d1", label: "Oggi" },
    { key: "d7", label: "7g" },
    { key: "d30", label: "30g" },
  ];
  const chips = windows
    .map((w) => {
      const b = totals[w.key] || { pnl: 0, trades: 0 };
      return `<div class="pnl-chip">
        <span class="lbl">${w.label}</span>
        <span class="val ${pnlClass(b.pnl)}">${fmtMoney(b.pnl)}</span>
        <span class="sub">${b.trades || 0} trade</span>
      </div>`;
    })
    .join("");
  const err = (acc.sources && acc.sources.error) || null;
  const note = err
    ? `<div class="detail">journal non leggibile: ${esc(err)}</div>`
    : acc.start_date
      ? `<div class="detail">storico dal ${esc(acc.start_date)}</div>`
      : "";
  return `<div class="card account-card">
    <div class="head">
      <span class="name">${esc(acc.label || acc.id)}</span>
      <span class="badge">${esc(acc.id)}</span>
    </div>
    <div class="equity-head">
      <div>
        <div class="equity-label">Equity</div>
        <div class="equity-value">${latest ? latest.equity.toFixed(2) : "—"}</div>
      </div>
      <div>
        <div class="equity-label">Oggi</div>
        <div class="equity-delta ${pnlClass(delta)}">${
          delta === null || delta === undefined ? "—" : fmtMoney(delta)
        }</div>
      </div>
      <div>
        <div class="equity-label">Floating</div>
        <div class="equity-value sm ${pnlClass(latest && latest.floating)}">${
          latest ? fmtMoney(latest.floating) : "—"
        }</div>
      </div>
      <div>
        <div class="equity-label">Aperti</div>
        <div class="equity-value sm">${latest ? String(latest.open_positions) : "—"}</div>
      </div>
    </div>
    <svg class="equity-chart" viewBox="0 0 320 72" preserveAspectRatio="none">${sparkline(
      equity.points
    )}</svg>
    <div class="pnl-totals">${chips}</div>
    ${note}
  </div>`;
}

function renderAccounts(accounts) {
  const html = (accounts || []).map(accountCard).join("");
  $("accounts").innerHTML = html || '<div class="card">Nessun conto configurato</div>';
}

function renderChannels(channels) {
  const html = (channels || [])
    .map((ch) => {
      const t = ch.today || {};
      const p = (ch.pnl && ch.pnl.today) || { pnl: 0, trades: 0, win_rate: null };
      const p7 = (ch.pnl && ch.pnl.d7) || { pnl: 0, trades: 0 };
      const ex = ch.exec || { executed: 0, cancelled: 0 };
      const last = ch.last_emitted || ch.last_event;
      const lastHtml = last
        ? `<div class="lastmsg">
             ${fmtTs(last.ts_utc)} —
             ${last.action ? `<span class="action">${esc(last.action)}</span> · ` : ""}
             ${esc(last.outcome || "")}<br>${esc(last.raw_text || "")}
           </div>`
        : `<div class="lastmsg">Nessun evento bridge oggi</div>`;
      return `<div class="card channel-card">
        <div class="head">
          <span class="name ${ch.enabled ? "" : "disabled"}">${esc(ch.name)}</span>
          <span class="badge">${esc(ch.id)}</span>
        </div>
        <div class="pnl-row">
          <span class="pnl-big ${pnlClass(p.pnl)}">${fmtMoney(p.pnl)}</span>
          <span class="pnl-meta">oggi · ${p.trades || 0} chiusi
            ${p.win_rate != null ? " · WR " + p.win_rate + "%" : ""}</span>
        </div>
        <div class="counts">
          <span>7g <b class="${pnlClass(p7.pnl)}">${fmtMoney(p7.pnl)}</b></span>
          <span class="em">Segnali <b>${t.emitted ?? 0}</b></span>
          <span>Eseguiti <b>${ex.executed ?? 0}</b></span>
          <span class="er">Annullati <b>${ex.cancelled ?? 0}</b></span>
        </div>
        ${lastHtml}
      </div>`;
    })
    .join("");
  $("channels").innerHTML = html || '<div class="card">Nessun canale configurato</div>';
}

function renderOpens(accounts) {
  const rows = [];
  (accounts || []).forEach((acc) => {
    (acc.open_positions || []).forEach((o) => rows.push({ ...o, account: acc.label || acc.id }));
  });
  if (!rows.length) {
    $("opens").innerHTML = '<tr><td class="raw">Nessuna posizione aperta (da journal)</td></tr>';
    return;
  }
  rows.sort((a, b) => String(b.open_time_utc || "").localeCompare(String(a.open_time_utc || "")));
  $("opens").innerHTML = rows
    .map(
      (o) => `<tr>
        <td class="ts">${fmtTs(o.open_time_utc)}</td>
        <td class="ch">${esc(o.account)}</td>
        <td class="ch">${esc((o.channel || "").replace("CH_", ""))}</td>
        <td>${esc(o.direction)} ${esc(o.symbol)} · ${esc(o.volume)}</td>
        <td class="raw">@${esc(o.fill)} SL ${esc(o.sl)} TP ${esc(o.tp)}
          · ticket ${esc(o.ticket)} · ${esc(o.signal_id)}</td>
      </tr>`
    )
    .join("");
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
    const accounts = data.accounts && data.accounts.length
      ? data.accounts
      : [{ id: "main", label: "Conto", pnl: data.pnl, equity: data.equity,
           open_positions: data.open_positions, sources: data.sources }];
    renderLights(data.lights || {});
    renderAccounts(accounts);
    renderChannels(data.channels || []);
    renderOpens(accounts);
    renderEvents(data.events || []);
  } catch (err) {
    $("updated").textContent = "offline?";
    $("overall").className = "overall-dot dot crit";
  }
}

refresh();
setInterval(refresh, 15000);
