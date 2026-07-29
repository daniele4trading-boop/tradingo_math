# TG TradinGo Monitor Webapp

Dashboard mobile per monitorare bridge, MT5, link Gamehosting, canali e **PnL**.
**Fase 1:** semafori + eventi bridge. **Fase 2:** PnL per canale, posizioni aperte,
equity curve, stats esecuzione EA. Fase 3 (ordini) predisposta ma disabilitata
(`orders_enabled: false`).

## Architettura

- Processo Python unico (FastAPI + uvicorn) su **Contabo**, porta `8600`.
- Collector in thread background (refresh 15s), tutte le letture UNC con timeout.
- Accesso **solo via Tailscale**. Telefono/PC: `http://100.110.249.72:8600`.

## Sicurezza

- Login utente/password (hash PBKDF2-SHA256, 200k iterazioni).
- Sessione cookie HMAC firmato, scadenza 12h.
- Rate limit: 5 tentativi falliti → blocco 15 min + honeypot antibot.
- `webapp_config.json` solo sul VPS (non in git).

## Setup Contabo (una tantum)

```powershell
cd C:\TG_TradinGo
pip install -r requirements.txt
Copy-Item webapp_config.example.json webapp_config.json
python -m webapp.hash_password
C:\TG_TradinGo\start_webapp.bat
```

## Fase 2 — fonti dati

Da `checks.ea_journal_dir` (MQL5\\Files\\journal):

| Path | Uso |
|------|-----|
| `trades\trades_YYYYMMDD.csv` | PnL chiuso oggi/7g/30g, posizioni aperte |
| `equity\equity_YYYYMMDD.csv` | equity, floating, sparkline |
| `..\tradingo_signal_stats.csv` | eseguiti vs annullati |

Tag EA `ORO` / `GOLD` / `IT` / `AS` → normalizzati a `CH_*`.

## Aggiornamento (senza rifare password)

```powershell
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\pull_and_deploy_tg_tradingo.ps1 -Branch cursor/journal-and-exit-hardening-8e22
# Ctrl+C sulla finestra webapp, poi:
C:\TG_TradinGo\start_webapp.bat
```

Opzionale in `webapp_config.json` (se manca):

```json
"pnl_lookback_days": 30,
"equity_days": 3,
"checks": {
  "signal_stats": "C:\\Users\\Administrator\\AppData\\Roaming\\MetaQuotes\\Terminal\\AE2CC2E013FDE1E3CDF010AA51C60400\\MQL5\\Files\\tradingo_signal_stats.csv"
}
```

## Test

```bash
cd tg_tradingo && python -m pytest tests/test_webapp.py tests/test_webapp_pnl.py -v
```
