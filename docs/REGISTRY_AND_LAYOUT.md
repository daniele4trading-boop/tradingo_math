# Registry unico e separazione operativa

## Cos'e' il registry unico dei sistemi

Il registry e' il file:

```text
config/systems_registry.json
```

E' l'inventario centrale che dice alla dashboard e agli script:

- quali sistemi esistono;
- dove sono sulla VPS;
- quale file avviare;
- come riconoscere il processo in esecuzione;
- broker, account, server e magic number;
- quali log leggere;
- se il sistema e' live, dashboard, bridge, backtest o tool.

In pratica sostituisce la memoria sparsa tra cartelle, appunti e terminali.

## Cosa posso fare io

Posso:

- aggiungere nuovi sistemi al registry;
- correggere percorsi;
- collegare start/stop/restart alla dashboard;
- creare config modificabili;
- aggiungere log e PID;
- integrare nuove strategie e backtest;
- preparare backup e deploy.

## Cosa deve fare Daniele

Solo le cose che richiedono conferma umana o accesso fisico:

1. confermare se un conto e' reale, demo o prop;
2. confermare quali sistemi possono essere fermati/riavviati;
3. fornire eventuali file TXT delle strategie;
4. abilitare SSH/WinRM una volta via RDP se il Cloud Agent non puo' farlo in modo affidabile;
5. confermare parametri di rischio non presenti nel codice.

## Separazione chiara

```text
systems/
  live/          # inventario e note sui sistemi live, non duplicati con credenziali
strategies/
  registry.json  # strategie estratte dai TXT
backtest/
  engine.py
  strategies/
  data/
config/
  systems_registry.json
  systems_config.json
logs/
scripts/
dashboard/
```

## Regola importante

I sistemi live non vengono spostati o modificati di colpo. Prima si crea il control plane, poi si migra un sistema alla volta:

1. registry;
2. start/stop/status;
3. lettura config centralizzata;
4. test;
5. solo dopo modifica logica.
