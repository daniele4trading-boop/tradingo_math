# Repository tradingo_system — guida per agenti AI

Questa repo GitHub (`daniele4trading-boop/tradingo_system`) contiene **due sistemi** sulla stessa VPS:

| Sistema | Path repo | Path VPS | Documentazione agenti |
|---------|-----------|----------|---------------------|
| **TG TradinGo** (Telegram → MT5 copy) | `tg_tradingo/` | `C:\TG_TradinGo\` | [`tg_tradingo/AGENTS.md`](tg_tradingo/AGENTS.md) |
| **StatArb** (pairs trading MT5) | root (`core/`, `engine/`, …) | `C:\StatArb\` | [`CHECKLIST_LUNEDI.md`](CHECKLIST_LUNEDI.md), moduli 0–8 |

## Prima di lavorare

1. Identifica quale sistema modifica l'utente (TradinGo vs StatArb).
2. Per TradinGo: leggi `tg_tradingo/AGENTS.md` e i fixture in `tg_tradingo/docs/fixtures/`.
3. **Non committare** segreti: `tradingo_config.json`, `accounts.json`, `.env`.
4. VPS: `144.91.76.28`, SSH porta `2222`, utente `Administrator`.

## Sync TradinGo

```powershell
# VPS → repo (prima del commit)
C:\StatArb\scripts\import_tg_tradingo_to_repo.ps1

# repo → VPS (dopo pull)
C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1
```
