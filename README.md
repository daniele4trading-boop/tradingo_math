# TradinGO System

Control plane operativo per gestire i sistemi di trading TradinGO sulla VPS Windows.

Questa repo resta la base unica (`tradingo_system`) per:

- censire i sistemi live;
- modificare parametri in modo ordinato;
- avviare, fermare e riavviare engine Python;
- tenere separati sistemi live, strategie, backtest, config, log e script;
- preparare backup verso OneDrive locale quando la repo viene eseguita sul PC di Daniele.

## Layout

```text
config/
  systems_registry.json     # registro unico dei sistemi
  systems_config.json       # parametri modificabili dalla dashboard
dashboard/
  app.py                    # dashboard Streamlit unificata, porta 8502
scripts/
  start_all.ps1
  stop_all.ps1
  status.ps1
  restart.ps1
  deploy.ps1
  backup_to_onedrive.ps1
  install_service.ps1
backtest/
  engine.py
  strategies/
  data/
systems/
  live/README.md
logs/
```

I file Python storici in root restano invariati per compatibilita'. La nuova struttura li gestisce tramite registry e script, senza spostarli in questa prima fase.

## Avvio dashboard unificata

Su VPS:

```powershell
cd C:\tradingo_system
streamlit run dashboard\app.py --server.port 8502 --server.address 0.0.0.0
```

La dashboard legge:

- `config/systems_registry.json` per sapere quali sistemi esistono;
- `config/systems_config.json` per parametri e broker;
- `logs/*.pid` per stato processi;
- i log configurati nel registry.

## Backup OneDrive

Sul PC locale di Daniele, quando questa repo e' clonata o sincronizzata:

```powershell
.\scripts\backup_to_onedrive.ps1
```

Destinazione predefinita:

```text
C:\Users\danie\OneDrive\DANIELE\TRADINGO 2026
```

Da Cloud Agent non posso scrivere direttamente sul PC locale se quel percorso non e' montato sulla VPS o nella sessione remota.
