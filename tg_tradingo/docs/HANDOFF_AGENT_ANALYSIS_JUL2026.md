## 0. Sticky — prima di altre modifiche codice

**Deploy pendente utente:**
1. Bridge **v2.05** (anti-duplicazione OPEN su EDIT + ORO same-setup + IVAN `USCIAMO ORA`)
2. EA **v2.09** (stack solo con JSON `allow_stack` + BE buffer anti-10016)

```powershell
cd C:\StatArb
git fetch origin cursor/tg-tradingo-hardening-8e22
git reset --hard origin/cursor/tg-tradingo-hardening-8e22
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1
C:\TG_TradinGo\start_tradingo.bat
```

MetaEditor → `TG_TradinGoEA.mq5` → **F7** → log `EA v2.09 started` + `stack_opens=true (requires JSON allow_stack)`.  
Bridge log: `TG TradinGo Bridge v2.05`.

**Bug 24/07 (risolto in v2.05/v2.09):** `InpStackOpensIfFlatBusy` stackava ogni MSG+EDIT → IVAN 4×4=16, ORO 4 sell, STARK 2 buy. Ora l’EA stacka solo se `allow_stack:true` (ORO “Rientriamo”); gli EDIT OPEN diventano `UPDATE_OPEN`.

---

# Handoff per agente — analisi performance e miglioramenti TG TradinGo

Documento creato il **2026-07-22** per continuare il lavoro **senza intervento manuale dell’utente** su codice, test, PR e (ove possibile) deploy. L’utente ha chiesto analisi canale-per-canale su log **20–22 luglio 2026** e fix di sistema.

---

## 1. Contesto repository

| Elemento | Valore |
|----------|--------|
| Repo | `daniele4trading-boop/tradingo_system` |
| Sistema | **TG TradinGo** sotto `tg_tradingo/` (non confondere con StatArb in root) |
| Guida agenti | `tg_tradingo/AGENTS.md`, root `AGENTS.md` |
| Branch lavoro recente | `cursor/tg-tradingo-hardening-8e22` (base: `main`) |
| VPS produzione | `144.91.76.28:2222`, utente `Administrator` |
| Path VPS bridge | `C:\TG_TradinGo\` |
| Path VPS repo pull | `C:\StatArb\` |

**Non committare mai:** `tradingo_config.json`, `accounts.json`, `.env`, sessioni Telegram, API hash reali.

---

## 2. Stato versioni (repo al handoff)

| Componente | Versione | Note |
|------------|----------|------|
| Bridge | **v2.05** (`tradingo_bridge.py`, `start_tradingo.bat`) | EDIT→UPDATE_OPEN + ORO same-setup + USCIAMO ORA |
| EA | **v2.09** (`mql5/TG_TradinGoEA.mq5`) | stack solo con `allow_stack` + BE buffer |
| Canali config esempio | CH_GOLD, CH_FOREX, CH_ORO, CH_STARK, CH_IVAN | Parser `ivan_vip` in `tradingo_config.example.json` |

Produzione utente aveva EA **v2.04** poi **v2.05**; bridge **v2.02**; Ivan aggiunto manualmente in `InpChannels` su MT5 prima che il default EA includesse `ivan`.

---

## 3. Cosa è stato fatto nella conversazione precedente

### Implementazioni già in repo (branch hardening)

- **FOREX:** pending `NEW ORDER` → `OPEN` solo su `Modified` con TP (`parser_sala_vip` + `bridge_core` forex pending).
- **ORO:** `Zona buy/sell X-Y` → `entry_range`; pending frammentati.
- **IvanTrades:** parser `ivan_vip` (OPEN 4 TP, `CHECK_AND_BE`, `CLOSE_ALL_SYMBOL`, `Meta size` → `lot_factor=0.5`).
- **EA v2.04:** commenti trade `TG-{CHANNEL}-T{n}`, CSV `tradingo_signal_stats.csv` esteso.
- **EA v2.05:** clear JSON dopo ogni segnale processato (evita replay al riavvio EA).
- **Utilità:** `fetch_date_range.py` (`--last`, `--parser`, `resolve_config_path`), `analyze_signal_stats.py`, test in `tests/test_parsers.py`.

### Analisi richiesta dall’utente (eseguita su log incollati, non su file VPS)

Periodo **2026-07-20 → 2026-07-22**: log MT5 Trades, log EA `[TradinGo]`, log bridge `C:\TG_TradinGo\logs\`.

**Fonti dati usate dall’analisi:** testo nella chat (nessun `tradingo_signal_stats.csv` caricato). File upload `luglio_2026_gold_m1_bba2.csv` = **OHLC M1 XAUUSD giugno**, non stats EA.

---

## 4. Risultati analisi (sintesi per priorità)

### Classifica canali (copy automatico reale, non “pips marketing”)

1. **STARK** — alta esecuzione; scalp TP stretti; 2 fallimenti `invalid stops` (22 lug 15:00).
2. **IVAN** — buona copertura parser; multi-TP; gap **METÀ SIZE** non riduce lotto.
3. **GOLD** — OPEN_NOW/UPDATE_OPEN ok; gap gestione **break even** / **partial closure**.
4. **ORO** — molti `SIGNAL_CANCELLED` (tolleranza 150 pt); recap canal non replicabile dal bot.
5. **FOREX** — nel periodo **0 OPEN** copiati (solo `UPDATE_TP` orfani).

### Problemi trasversali

- **Più istanze EA** (M1/M5/H1) + JSON non cleared (pre-v2.05) → doppie letture, `CLOSE_HALF_BE` duplicati.
- **WinError 5** su scrittura atomica `signal_ch_oro.json` (lock EA).
- **Hedging:** posizioni opposte XAUUSD da canali diversi → PnL netto ≠ somma pips per canale.
- **Deploy EA:** script `deploy_tg_tradingo_to_vps.ps1` **non** copia `mql5/` — EA va distribuito a mano o estendendo lo script.

### Bug parser confermati (da fixare)

| Canale | Messaggio | Problema |
|--------|-----------|----------|
| GOLD | `Partial closure break Even` | `contains_any("PARTIAL CLOSE")` **non** matcha `PARTIAL CLOSURE` (manca sotto-stringa `PARTIAL CLOSE` prima della `U`) |
| GOLD | `break Even` da solo | Ignorato da regex `BREAK\s*EVEN` in `ignore_pats` dopo check partial |
| GOLD | `Sell limit gold …` | Non supportato (solo market) |
| IVAN | `METÀ SIZE` / `SIZE` (22 lug) | Non imposta `lot_factor=0.5` (solo `Meta size`) |
| STARK/EA | OPEN con SL/TP troppo vicini al prezzo | MT5 err **10016** — normalizzare con `SYMBOL_TRADE_STOPS_LEVEL` |
| FOREX | NEW ORDER senza Modified | Verificare end-to-end che emetta `OPEN` dopo fix pending |

### Parametri EA

- `InpRangeTolerancePts=150` — troppo stretto per ORO (molti cancel 151–800 pt distance).
- Valutare tolleranza **per canale** o 200–250 pt solo CH_ORO.

---

## 5. Missione per il prossimo agente

### Obiettivo A — Analisi quantitativa (preferita)

1. Ottenere dati reali (ordine di preferenza):
   - `tradingo_signal_stats.csv` da `MQL5\Files\` sul terminale VPS (path in log EA).
   - Export storico MT5 con **Comment** (`TG-GOLD-T1`, …) e **Magic**.
   - Log bridge `C:\TG_TradinGo\logs\tradingo_YYYYMMDD.log`.
2. Eseguire in repo:
   ```bash
   cd tg_tradingo
   python analyze_signal_stats.py --stats /path/to/tradingo_signal_stats.csv
   python fetch_date_range.py --channel CH_GOLD --last 100 --parser sala_gold  # dry-run se implementato
   pytest tests/test_parsers.py -q
   ```
3. Produrre report: per canale — segnali bridge OPEN vs EA executed/cancelled, win rate, pips stimati, drawdown, confronto con messaggi “+N pips” Telegram.
4. Se SSH VPS è disponibile dall’ambiente cloud, scaricare i file; altrimenti documentare nel PR cosa manca e usare `fetch_date_range` con config produzione (`resolve_config_path`).

### Obiettivo B — Fix codice (autonomo, senza chiedere conferma utente)

Implementare in branch `cursor/<nome-descrittivo>-8e22`:

1. **GOLD** (`parser_sala_gold` in `tradingo_bridge.py`):
   - Trattare `PARTIAL CLOSURE` come partial close.
   - Dopo trade aperto: `break even` / `breakeven` senza “partial” → `CLOSE_HALF_BE` o `BREAK_EVEN` (allineare a fixture in `docs/fixtures/signals_apr21.txt`).
   - Test in `tests/test_parsers.py`.
2. **IVAN** (`parser_ivan_vip`): `METÀ SIZE`, `MEZZA SIZE`, `META SIZE` (varianti) → `lot_factor=0.5`.
3. **Bridge:** retry 3–5 volte su `atomic_write` se `PermissionError` / WinError 5 (backoff ms).
4. **EA (opzionale v2.06):** validazione distanza minima SL/TP prima di `OrderSend`; input opzionale tolleranza per `channel_id` ORO.
5. Bump versioni: bridge **v2.03**, EA **v2.06** se tocchi EA; aggiornare `docs/EA_SPEC.md`, `start_tradingo.bat`.

**Non fare senza esplicita richiesta utente:** cambiare lotti globali, disabilitare canali in config produzione, trading live su conto reale.

---

## 6. Workflow Git / PR (agente cloud)

1. `git fetch origin main && git checkout -b cursor/<task>-8e22 origin/main` (o continuare su `cursor/tg-tradingo-hardening-8e22` se correlato).
2. Commit atomici con messaggi chiari; **no segreti**.
3. `git push -u origin <branch>`.
4. `ManagePullRequest`: `create_pr` o `update_pr`, `branch_name`, `base_branch: main`, draft ok.
5. Prima di chiudere il turno: push + update PR.

---

## 7. Deploy produzione VPS (minimo intervento umano)

### Bridge Python (automatizzabile da VPS dopo `git pull`)

Sulla VPS (PowerShell):

```powershell
cd C:\StatArb
git pull origin <branch-mergeato-o-branch-test>
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1
# Riavvio bridge: chiudere finestra start_tradingo.bat e rilanciare
C:\TG_TradinGo\start_tradingo.bat
```

Lo script **non** sovrascrive `tradingo_config.json` né `state/*.json`.

### EA MT5 (richiede azione su Windows VPS)

1. Copiare `tg_tradingo/mql5/TG_TradinGoEA.mq5` → `MQL5\Experts\` del terminale (ID terminale in log: `AE2CC2E013FDE1E3CDF010AA51C60400`).
2. **Compilare in MetaEditor** (F7) — non c’è compile headless documentato in repo.
3. Un **solo** grafico con EA attivo (consigliato XAUUSD H1); `InpChannels` = `gold,forex,oro,stark,ivan` (o default v2.05).
4. Verificare `InpClearSignalAfterProcess=true`.

**Miglioramento per agenti:** estendere `deploy_tg_tradingo_to_vps.ps1` per copiare `mql5\TG_TradinGoEA.mq5` nella cartella Experts (senza compilare).

### Config canali

- `CH_IVAN`: in produzione deve avere `"parser": "ivan_vip"` e `enabled: true` in `C:\TG_TradinGo\tradingo_config.json` (solo su VPS, non in git).

---

## 8. File chiave nel codice

| File | Ruolo |
|------|--------|
| `tg_tradingo/tradingo_bridge.py` | Parser + versione bridge |
| `tg_tradingo/bridge_core.py` | Stato pending, `apply_lot_rules`, `resolve_config_path`, scrittura JSON |
| `tg_tradingo/mql5/TG_TradinGoEA.mq5` | EA |
| `tg_tradingo/tests/test_parsers.py` | Test parser |
| `tg_tradingo/fetch_date_range.py` | Dump Telegram + dry-run parser |
| `tg_tradingo/analyze_signal_stats.py` | Aggregazione CSV EA |
| `tg_tradingo/docs/CHANNEL_MAP.md` | Magic, lotti, flussi |
| `tg_tradingo/docs/EA_SPEC.md` | Contratto JSON |
| `scripts/deploy_tg_tradingo_to_vps.ps1` | Deploy code → `C:\TG_TradinGo` |

---

## 9. Messaggi utente ancora aperti (opzionale)

- Confronto pips annunciati vs deal MT5 **per trade** (serve CSV stats o history export).
- Analisi **Sala Gold** su messaggi ignorati (priorità: break even / partial closure).
- Ranking definitivo con win rate e drawdown in valuta.

---

## 10. Checklist agente “fine turno”

- [x] `pytest tg_tradingo/tests/` (54 passed — GOLD/IVAN/atomic_write Jul 2026)
- [x] Versioni bridge **v2.03** / EA **v2.06**
- [x] Report analisi: `docs/ANALYSIS_JUL20_22_2026.md`
- [x] PR aggiornata: https://github.com/daniele4trading-boop/tradingo_system/pull/19
- [x] Istruzioni deploy in PR description (pull + deploy ps1 + riavvio bridge; nota compile EA)
- [x] Nessun segreto nel diff

---

*Fine handoff — conversazione origine: analisi log 20–22 lug 2026, hardening bridge/EA Ivan/FOREX/ORO, clear JSON v2.05.*
