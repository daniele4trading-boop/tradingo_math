# Scalping — Win% vs Non-loss% (Test 1 reverse engine)

**Non-loss%** = trade con `pnl > 0`, oppure `pnl = 0` (BE), oppure **TP1 toccato** (inclusi TP1 → SL/BE sul residuo).

| Profilo | Side | Trade | Win% | TP1% | TP1→SL% | **Non-loss%** | No full SL% | Full SL% | Exp | PnL |
|---------|------|-------|------|------|---------|---------------|-------------|----------|-----|-----|
| SCALPING_LIMIT | ORIG | 451 | 18.4% | 35.7% | 17.29% | **35.7%** | 35.7% | 64.3% | -0.285R | -12854.25 |
| SCALPING_LIMIT | REV | 1335 | 2.92% | 4.79% | 1.87% | **4.79%** | 4.79% | 95.21% | -0.891R | -118996.14 |
| SCALPING_MARKET | ORIG | 543 | 14.0% | 29.47% | 15.47% | **29.47%** | 29.47% | 70.53% | -0.52R | -28261.21 |
| SCALPING_MARKET | REV | 579 | 15.72% | 30.22% | 14.51% | **30.22%** | 30.22% | 69.78% | -0.529R | -30658.03 |

### Legenda

- **Win%**: solo `pnl_r > 0`
- **Non-loss%**: win + BE piatto + qualsiasi trade che ha toccato TP1
- **TP1→SL%**: TP1 raggiunto, chiusura finale su SL (tipico BE sul 50% residuo)
- **No full SL%**: non ha perso -1R intero
- **Full SL%**: stop out completo (~-1R)