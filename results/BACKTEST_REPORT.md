# LQS-MTF Backtest Report

**Data:** 2026-06-29  
**Strategia:** Liquidity Quest Structure Multi-Timeframe (LQS-MTF)  
**Simbolo:** XAUUSD  
**Periodo dati:** 2026-02-24 → 2026-06-05 (~3.3 mesi, 99.750 barre M1)

---

## Fonti dati

| Fonte | Path | Note |
|-------|------|------|
| **VPS Ultima Markets** (primaria) | `data/XAUUSD/M1/2026-02.csv` … `2026-06.csv` | Scaricati via SCP da `C:\TradinGO_Research\data_ultima\XAUUSD\M1` |
| **VPS STARTRADER** | `data/XAUUSD/M1/2026-05.csv`, `2026-06.csv` | Sovrapposti ai file Ultima (stesso naming) |
| **Parquet repo** (fallback) | `tradingo_lab/data/rates/XAUUSD/M1/*.parquet` | Feb–Mag 2026, copertura parziale |
| **Dukascopy** | `/tmp/dukascopy_xau_m1_2026/` | Non usato in questo run; necessario per gap 06–25/06 |

**Formato CSV broker:** `time,open,high,low,close,tick_volume,spread,real_volume` (UTC)

---

## Architettura implementata

```
strategies/
  structure.py    # fractals, equal highs, sweep, BOS, FVG, sessioni
  lqs_mtf.py      # logica setup H4→H1→M15, entry 50%+emissione
backtest/
  data_loader.py  # load CSV, resample M1→M5/M15/H1/H4
  engine.py       # replay M5, limit fill, SL/TP parziali
  metrics.py      # win rate, PF, DD, expectancy
scripts/
  run_backtest.py # CLI principale
```

**Integrazione futura:** `LQSMtfStrategy.try_signal()` può mappare su `Signal` enum in `tradingo_system.py`. Parametri in `config.json` → sezione `lqs_mtf`.

---

## Regole di simulazione

- Spread: 65 pt (0.65 USD) — da `config.json`
- Slippage limit: 0.10 USD per lato
- Fill limit: se `low <= limit <= high` sulla barra M5
- SL prioritario se SL e TP nella stessa barra (conservativo)
- No lookahead: solo barre chiuse; sweep registrati su chiusura H1; conferma BOS su ogni barra M5
- Sessioni: London 09–12, NY 15–20 (broker UTC+2)
- Rischio fisso: 100 USD/trade (1R)

---

## Risultati principali

| Metrica | Valore |
|---------|--------|
| **Trade totali** | 41 |
| **Win rate** | 29.27% |
| **Expectancy** | -0.347 R/trade |
| **Profit factor** | 0.449 |
| **Max drawdown** | -14.37% |
| **PnL netto** | -1.422 USD (a 100 USD/R) |
| **Long / Short** | 20 / 21 |
| **TP1 hit** | 39.02% |
| **TP2 hit** | 39.02% |
| **TP3 hit** | 29.27% |

### Breakdown per sessione

| Sessione | Trade | Expectancy (R) | PnL (R) |
|----------|-------|----------------|---------|
| London | 7 | -0.89 | -6.2 |
| NY | 17 | -0.67 | -11.4 |
| Other | 17 | +0.20 | +3.4 |

---

## Trade esempio (commentati)

### 1. SHORT — sweep H1 + BOS M15
- **Motivo:** `SHORT sweep@2945.50 bos@...`
- **Logica:** equal highs su H1 violati con wick; M15 rompe swing low; entry al 50% del displacement
- **Esito tipico:** SL o TP1 parziale a seconda del ritracciamento

### 2. LONG — sweep liquidità sotto minimi
- **Motivo:** sweep di swing low H1 + CHoCH rialzista M15
- **Entry:** limit arrotondato a step 0.50 USD
- **SL:** sotto estremo sweep + 0.2×ATR(H1)

### 3. Gestione parziale
- 50% a TP1 (~1.5R), 30% a TP2 (FVG/struttura), 20% a TP3 (3R)
- Breakeven dopo TP1

---

## Punti di forza emersi

1. **Pipeline oggettiva funzionante:** sweep → BOS → zona entry → backtest ripetibile
2. **Frequenza realistica:** ~12 trade/mese (selettivo, non overtrading)
3. **Bilanciamento long/short:** 20 vs 21
4. **Dati broker reali** da VPS Ultima, non sintetici

## Punti di debolezza emersi

1. **Expectancy negativa** con parametri default: win rate 29% insufficiente per RR medio
2. **Sessioni London/NY underperformano** vs orario "Other" — filtro sessione da rivedere
3. **Sweep detection** ancora sensibile: alcuni falsi sweep su swing singoli
4. **Gap dati:** nessun dato dopo 05/06/2026; serve Dukascopy per giugno
5. **Runtime backtest:** ~5 min su 100k barre M1 (ottimizzabile)

---

## Parametri attuali (`config.json` → `lqs_mtf`)

| Parametro | Valore |
|-----------|--------|
| sweep_atr_mult | 0.3 |
| impulsive_body_ratio | 0.55 |
| equal_highs_tolerance_atr | 0.5 |
| min_rr | 1.5 |
| limit_expire_bars_m5 | 12 |
| session_filter | true |

---

## Ottimizzazione parametri (2026-06-30)

### Metodo
- Random search: 20 combinazioni su universo di 4.374
- Refine: 16 perturbazioni one-at-a-time sul miglior train
- Walk-forward: train Mar–Apr 2026, test Mag–Giu 2026
- Script: `scripts/optimize_lqs.py`

### Migliori parametri (train Mar–Apr)

| Parametro | Default | Ottimizzato |
|-----------|---------|-------------|
| sweep_atr_mult | 0.3 | **0.3** |
| equal_highs_tolerance_atr | 0.5 | **0.5** |
| min_rr | 1.5 | **2.0** |
| session_filter | true | **true** |
| limit_expire_bars_m5 | 12 | **12** |
| max_setup_age_bars_h1 | 8 | **6** |
| sl_atr_buffer_mult | 0.2 | **0.25** |

### Risultati confronto (full sample Feb–Giu)

| Metrica | Default | Ottimizzato |
|---------|---------|-------------|
| Trade | 41 | **9** |
| Win rate | 29.3% | 22.2% |
| Expectancy | -0.35 R | **+0.34 R** |
| Profit factor | 0.45 | **1.44** |
| Max DD | -14.4% | **-2.8%** |
| PnL netto | -1.423 USD | **+308 USD** |

### Note importanti
- **OOS non confermato:** tutte le top-5 config train hanno fallito su Mag–Giu (mercato diverso)
- Campione ridotto: 9 trade in 3 mesi — serve più dati (Dukascopy giugno) per validare
- Train Mar–Apr mostrava expectancy +1.01 R su 6 trade (possibile overfitting)
- Parametri salvati in `config.json` → `lqs_mtf`

---

## Prossimi passi consigliati

1. **Grid search** su `sweep_atr_mult`, `min_rr`, `session_filter` (walk-forward 6+2 mesi)
2. **Unire Dukascopy giugno** per copertura 08–25/06
3. **Confronto costi broker** con `C:\tsentry_repo\tsentry_broker_costs.py` sulla VPS
4. **Filtro H4 più restrittivo** per eliminare counter-trend deboli
5. **Paper test** prima di hook live su `tradingo_system.py`

---

## Comandi

```bash
# Backtest
PYTHONPATH=/workspace python3 scripts/run_backtest.py --data-dir data/XAUUSD/M1

# Test unitari
PYTHONPATH=/workspace python3 -m pytest tests/ -q

# Download Dukascopy (gap giugno)
npx --yes dukascopy-node -i xauusd -from 2026-01-01 -to 2026-06-26 -t m1 -p bid -f csv -v \
  -dir /tmp/dukascopy_xau_m1_2026 -r 3 -rp 2000 -bs 10 -bp 1000
```

---

## Parametri ancora soggettivi

- Scelta "ultima emissione" in zone dense di candele
- Definizione supply/demand H4 (attualmente: top/bottom 20% del range)
- Wyckoff completo (non implementato; approssimato con sweep+BOS)
- Number Theory rounding (solo step 0.50)
