# TG TradinGo Monitor Webapp

Dashboard mobile per monitorare bridge, MT5, link Gamehosting e canali.
**Fase 1: sola lettura** (semafori + eventi). Fase 3 (ordini) predisposta ma
disabilitata (`orders_enabled: false`).

## Architettura

- Processo Python unico (FastAPI + uvicorn) su **Contabo**, porta `8600`.
- Collector in thread background (refresh 15s), tutte le letture UNC con timeout:
  la pagina resta veloce anche se la share Tailscale e' giu'.
- Accesso **solo via Tailscale** (nessuna porta pubblica). Dal telefono:
  installa Tailscale, stessa tailnet, apri `http://100.110.249.72:8600`.

## Sicurezza

- Login utente/password (hash PBKDF2-SHA256, 200k iterazioni).
- Sessione cookie HMAC firmato, scadenza 12h (config `session_hours`).
- Rate limit: 5 tentativi falliti per IP/utente → blocco 15 min.
- Honeypot antibot nel form; `noindex`; niente docs/openapi esposti.
- Niente segreti in git: `webapp_config.json` resta solo sul VPS.

## Setup su Contabo (una tantum)

```powershell
cd C:\TG_TradinGo
pip install -r requirements.txt

# 1. crea il config
Copy-Item webapp_config.example.json webapp_config.json

# 2. genera hash password + secret_key e incollali in webapp_config.json
python -m webapp.hash_password

# 3. avvia
C:\TG_TradinGo\start_webapp.bat
```

Autostart (facoltativo, come il bridge):

```powershell
$act = New-ScheduledTaskAction -Execute "C:\TG_TradinGo\start_webapp.bat" -WorkingDirectory "C:\TG_TradinGo"
$trg = New-ScheduledTaskTrigger -AtLogOn
$trg.Delay = "PT120S"
Register-ScheduledTask -TaskName "TG_TradinGo_WebappAtLogon" -Action $act -Trigger $trg -Force
```

## Semafori

| Card | Verde | Giallo | Rosso |
|------|-------|--------|-------|
| Bridge Telegram | heartbeat < 90s | < 180s | oltre / file mancante |
| MT5 locale | terminal64 attivo + journal EA fresco | journal fermo/assente | terminale spento |
| Link Gamehosting | ping + share ok | — | ping o share KO |
| Heartbeat su share | come bridge ma letto da `\\100.74.9.8\tradingo` | | |

Canali: conteggi giornalieri dal journal `bridge_events` (EMITTED / ignorati /
UNPARSED / PARSE_ERROR) + ultimo segnale emesso.

## Config (`webapp_config.json`)

Vedi `webapp_config.example.json`. Campi principali: `users[]` (hash), `secret_key`,
`port`, `checks.*` (path heartbeat/journal, host/share amico, cartella journal EA
con l'hash del terminale MT5).

## Test

```bash
cd tg_tradingo && python -m pytest tests/test_webapp.py -v
```
