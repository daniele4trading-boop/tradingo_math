# Emission MTF — Backtest 4 varianti

**Periodo:** 2026-02-24 11:58:00+00:00 → 2026-06-05 23:56:00+00:00  
**Barre M1:** 99,750  
**Strategia:** dominance + B2S/S2B (video DO7kdX-dByE)

## Confronto

| Profilo | Stile | Metodo | Contesto | Exec | Trade | Win% | Exp | PF | Max DD | PnL |
|---------|-------|--------|----------|------|-------|------|-----|-----|--------|-----|
| **SCALPING_LIMIT** | SCALPING | LIMIT | H4→H1 | M5 | 451 | 18.4% | -0.285R | 0.6 | -130.65% | -12854.25 |
| **SCALPING_MARKET** | SCALPING | MARKET | H4→H1 | M5 | 543 | 14.0% | -0.52R | 0.316 | -284.46% | -28261.21 |
| **INTRADAY_LIMIT** | INTRADAY | LIMIT | D1→H4 | H1 | 30 | 23.33% | 0.457R | 1.837 | -8.15% | 1372.28 |
| **INTRADAY_MARKET** | INTRADAY | MARKET | D1→H4 | H1 | 50 | 6.0% | -0.78R | 0.056 | -38.36% | -3897.54 |

## Profili

- **SCALPING_LIMIT**: H4→H1 contesto, M5 operativo, sell/buy limit su B2S/S2B
- **SCALPING_MARKET**: H4→H1 contesto, M5 operativo, engulfing/evening star in zona
- **INTRADAY_LIMIT**: D1→H4 contesto, H1 operativo, limit su emissione
- **INTRADAY_MARKET**: D1→H4 contesto, H1 operativo, pattern in zona emissione

Filtri discrezionali (fib, wyckoff) disattivati — da affinare in ottimizzazione.
