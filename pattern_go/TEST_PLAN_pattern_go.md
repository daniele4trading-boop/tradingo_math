# Test plan — Pattern GO (PR #38)

Tutto da riga di comando (nessuna GUI → nessuna registrazione). Vincolo: solo chiamate
in lettura al broker. `place_stop_order` / `cancel_order` / `close_position` solo contro
FakeClient (`tests/test_runner.py:54-64`).

Credenziali via env `DXTRADE_USERNAME` / `DXTRADE_PASSWORD` (mai su disco/report).
Cwd: `/home/ubuntu/repos/tradingo_system/pattern_go`.

## T1 — Lint e unit test
`python3 -m ruff check .` → "All checks passed"; `PYTHONPATH=. python3 -m pytest tests -q`
→ 79 passed, 0 failed.

## T2 — Dry-run reale contro conto demo (primario)
`cp config.example.json config.json`, poi
`PYTHONPATH=. python3 -m pattern_go --config config.json --dry-run` (exit 0).
Pass/fail su `logs/journal_YYYYMMDD.jsonl`:
- evento `STARTUP` presente con `symbol == "XAU"`, `quantity_increment == 0.01`,
  `balance == 10000.0`, `static_floor == 9700.0`, `reservoir == 300.0`,
  `risk_amount == 15.0`, `strategies == ["M15","M5"]` (`runner.py:125-136`)
- eventi `WARMUP` per M5 e M15 con `bars > 0` entrambi (`runner.py:138-152`)
- evento `RECONCILE` presente
- nessun evento `ORDER_PLACED`/`TRADE_OPENED`; nessuna POST /orders (verifico anche
  con `grep -c ORDER_ logs/*.jsonl` == 0)

## T3 — Nessun segreto nei log
`grep -R` di username, password e `sessionToken` (case-insensitive) su `logs/`,
`state/`, `reports/` e sull'output stdout catturato del dry-run → **0 occorrenze**.
Fail se compare anche una sola volta.

## T4 — Kill switch (FakeClient, nessun broker)
Script che usa `Runner` + FakeClient di `tests/test_runner.py`: startup, creo il file
KILL_SWITCH, `tick()`. Pass: journal contiene `KILL_SWITCH` con `closes: true`, e il
tick esce senza chiamare `quote`/piazzare ordini (`client.placed == []`).
Poi rimuovo il file e verifico che il tick successivo torni operativo (nessun ulteriore
evento KILL_SWITCH). Faccio anche un test con il vero file `KILL_SWITCH` in cwd via
config reale? No: solo FakeClient, per non toccare il broker.

## T5 — analyze_logs e report giornaliero su journal senza trade
`python3 -m pattern_go.analyze_logs --log-dir logs` e `--json` → exit 0, nessuna
eccezione/traceback, sezioni con `—` per le metriche assenti.
`write_daily_report` sul journal odierno (senza trade) → file `reports/report_*.md` e
`.json` creati, nessuna eccezione, tabella con 0 trade.

## T6 — Adversarial su config/credenziali (nessun ordine)
Per ognuno: exit code != 0, messaggio d'errore leggibile in una riga, nessun loop,
nessun retry infinito, nessun crash silenzioso. Registro il testo esatto dell'errore.
1. `DXTRADE_PASSWORD` errata → deve fallire su login con `AuthError` chiaro
   (`dxtrade.py:113-117`), 1 sola richiesta di login, non 5 retry
2. `DXTRADE_USERNAME` assente → `ValueError: variabile d'ambiente ... non impostata`
   (`config.py:74-76`), nessuna chiamata di rete
3. config senza `broker` / senza `risk` → KeyError con nome del campo
4. `risk_fraction: -0.05` → verifico se viene rifiutato o accettato silenziosamente
   (accettarlo è un difetto da segnalare: quantità/rischio negativi)
5. `initial_balance` tale che il floor > saldo (es. 20000) → serbatoio negativo:
   verifico che non produca quantità positive né ordini
6. `symbol: "XAUUSD_FAKE"` → `DXTradeError: strumento ... non trovato`
   (`dxtrade.py:188-189`), nessun ordine

## T7 — Coerenza barre di warmup su dati veri
Script read-only: `client.candles("XAU","M5"/"M15", now-400*tf)` +
`Runner._closed_bars`. Pass:
- timestamp strettamente crescenti
- nessuna barra con `time > now - tf_minutes` (nessuna barra in formazione)
- allineamento: minuti multipli di 5 (M5) e 15 (M15)
- buchi: elenco dei gap non multipli del timeframe, attesi solo su weekend/rollover
  (li riporto senza dichiarare fail se cadono su chiusure di mercato)

## T8 — Spread reale XAU
`python3 tools/spread_sampler.py --minutes 3 --interval 15 --account default:130000638
--out /tmp/spread_samples.jsonl` → riporto medio/mediano/min/max in punti e l'esito
PASSA/BLOCCATO per M5 e M15. Solo misura, nessun criterio di fail sul PR.
