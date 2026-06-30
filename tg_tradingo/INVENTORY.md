# Inventario `C:\TG_TradinGo` (snapshot apr 2026)

Elenco file trovati sulla VPS. Runtime non in git; sorgenti in `tg_tradingo/`.

## Codice → in git

- `tradingo_bridge.py`, `dump_channels.py`, `sample_channels.py`, `fetch_apr21.py`
- `start_tradingo.bat`, `README.md`, `AGENTS.md`
- `tradingo_config.example.json` (template; **non** il json con api_hash reale)
- `TG_TradinGoEA.mq5` — **non presente** in `C:\TG_TradinGo` (probabilmente in `MQL5\Experts\`)

## Log VPS (runtime, non in git)

- `logs/tradingo_20260413.log` … `tradingo_20260428.log`
- `logs/signal_samples.txt`, `channel_dump.txt`, `signals_apr21.txt` → copiati in `docs/fixtures/` via script import

## Aggiornare

```powershell
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\import_tg_tradingo_to_repo.ps1
```
