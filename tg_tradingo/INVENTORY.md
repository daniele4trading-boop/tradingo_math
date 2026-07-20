# Inventario `C:\TG_TradinGo` (snapshot apr 2026)

Elenco file trovati sulla VPS. Runtime non in git; sorgenti in `tg_tradingo/`.

## VPS / deploy

**TG_TradinGoEA.mq5** — in repo: `tg_tradingo/mql5/TG_TradinGoEA.mq5` (v2.0, lug 2026).  
Specifica JSON: `tg_tradingo/docs/EA_SPEC.md`. Setup amici: `tg_tradingo/docs/FRIEND_SETUP.md`.

Sulla VPS, per trovare eventuale EA legacy:

```powershell
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\find_tradingo_ea.ps1
```

| Percorso VPS | Ruolo |
|--------------|-------|
| `C:\StatArb\tg_tradingo\` | sviluppo git |
| `C:\TG_TradinGo\` | produzione bridge |
| `C:\TG_TradinGo\state\` | `bridge_state.json`, `processed_messages.json` |

Deploy: copiare `tradingo_bridge.py`, `bridge_core.py`, `start_tradingo.bat` in `C:\TG_TradinGo` **dopo backup**. Non sovrascrivere `tradingo_config.json`.

Script automatico (backup + deploy):

```powershell
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1
```

Opzioni: `-DryRun` (simula), `-SkipBackup` (salta backup).

## Codice → in git

- `tradingo_bridge.py`, `bridge_core.py`, `dump_channels.py`, `sample_channels.py`, `fetch_apr21.py`
- `start_tradingo.bat`, `requirements.txt`, `README.md`, `AGENTS.md`
- `tests/test_parsers.py`, `tests/test_bridge_core.py`
- `tradingo_config.example.json` (template; **non** il json con api_hash reale)
- `TG_TradinGoEA.mq5` — **non presente** in repo né in `C:\TG_TradinGo` (snapshot apr 2026).
  Cercare sotto `MQL5\Experts\` del terminale MT5 sulla VPS.

## Log VPS (runtime, non in git)

- `logs/tradingo_20260413.log` … `tradingo_20260428.log`
- `logs/signal_samples.txt`, `channel_dump.txt`, `signals_apr21.txt` → copiati in `docs/fixtures/` via script import

## Aggiornare

```powershell
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\import_tg_tradingo_to_repo.ps1
```
