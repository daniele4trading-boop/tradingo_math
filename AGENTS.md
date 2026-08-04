# Repository tradingo_system — guida per agenti AI

Questa repo GitHub (`daniele4trading-boop/tradingo_system`) contiene **tre sistemi** sulla stessa VPS:

| Sistema | Path repo | Path VPS | Documentazione agenti |
|---------|-----------|----------|---------------------|
| **TG TradinGo** (Telegram → MT5 copy) | `tg_tradingo/` | `C:\TG_TradinGo\` | [`tg_tradingo/AGENTS.md`](tg_tradingo/AGENTS.md) |
| **StatArb** (pairs trading MT5) | root (`core/`, `engine/`, …) | `C:\StatArb\` | [`CHECKLIST_LUNEDI.md`](CHECKLIST_LUNEDI.md), moduli 0–8 |
| **Pattern GO** (oro su DXtrade/Velotrade) | `pattern_go/` | `C:\PatternGO\` (non ancora deployato) | [`pattern_go/AGENTS.md`](pattern_go/AGENTS.md) |

## Prima di lavorare

1. Identifica quale sistema modifica l'utente (TradinGo vs StatArb vs Pattern GO).
2. Per TradinGo: leggi `tg_tradingo/AGENTS.md` e i fixture in `tg_tradingo/docs/fixtures/`.
3. Per Pattern GO: leggi `pattern_go/AGENTS.md`. È isolato dagli altri due, non aggiungere import incrociati.
4. **Non committare** segreti: `tradingo_config.json`, `accounts.json`, `.env`, `pattern_go/config.json`.
5. VPS: `144.91.76.28`, SSH porta `2222`, utente `Administrator`.

## Sync TradinGo

```powershell
# VPS → repo (prima del commit)
C:\StatArb\scripts\import_tg_tradingo_to_repo.ps1

# repo → VPS (dopo pull)
C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1
```
