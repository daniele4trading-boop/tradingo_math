# Fixture TG TradinGo

Campioni per sviluppo e test parser (estratti da VPS apr 2026).

| File | Descrizione |
|------|-------------|
| `signal_samples.txt` | Ultimi 50 messaggi per canale (CH1–CH4) |
| `signals_apr21.txt` | Messaggi 20–21 aprile per analisi |
| `channel_dump.txt` | Dump completo canali/gruppi |
| `signal_ch*_*.example.json` | Esempi payload JSON per azione |

Per aggiornare dalla VPS:

```powershell
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\import_tg_tradingo_to_repo.ps1
```
