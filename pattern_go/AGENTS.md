# Pattern GO — guida per agenti AI

Sistema **indipendente** dal resto della repo: trading su oro (`XAU`) via API DXtrade su
conto Velotrade PRO 1-Step 10k. Nessun import da `tg_tradingo/` o dai moduli StatArb, e
viceversa. Vedi [`README.md`](README.md) per architettura, regole del conto e assunzioni.

## Regole

1. **Nessun parametro di trading hardcoded**: soglie, filtri, sessioni e limiti di rischio
   vivono in `config.json` (esempio in `config.example.json`).
2. **Non committare** `config.json`, `logs/`, `reports/`, `state/`, `KILL_SWITCH`.
3. **Credenziali solo da variabili d'ambiente** (`DXTRADE_USERNAME`, `DXTRADE_PASSWORD`):
   non stampare password né `sessionToken` nei log.
4. **Il simbolo dell'oro è `XAU`** e la quantità è in once (`lotSize = 1.0`,
   `quantityIncrement = 0.01`): non riusare il modello "1 lotto = 100 once".
5. **Nessun ordine reale o demo senza autorizzazione esplicita dell'utente.**
6. `strategy.py` e `risk.py` restano **puri** (nessuna rete, nessun orologio): il tempo
   entra dalle barre, l'I/O sta in `dxtrade.py` e `runner.py`.
7. Ogni modifica alla logica di ingresso, uscita o sizing va coperta da test.

## Comandi

```bash
python3 -m ruff check .
PYTHONPATH=. python3 -m pytest tests -q
python3 -m pattern_go --config config.json --dry-run   # startup + warmup, nessun ordine
```
