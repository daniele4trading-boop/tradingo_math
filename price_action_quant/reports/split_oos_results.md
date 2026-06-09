# Price Action Quant v0.2 - Split/OOS Results

## Period clarification

The previous v0.1 results used Dukascopy BID OHLC data over:

- EURUSD H1: 2021-01-03 22:00 UTC to 2026-06-08 00:00 UTC.
- EURUSD H4: 2021-01-03 20:00 UTC to 2026-06-08 00:00 UTC.
- GBPUSD H1: 2021-01-03 22:00 UTC to 2026-06-08 00:00 UTC.
- GBPUSD H4: 2021-01-03 20:00 UTC to 2026-06-08 00:00 UTC.

This v0.2 report uses:

- In-sample: bars before 2024-01-01 00:00 UTC.
- Out-of-sample: bars from 2024-01-01 00:00 UTC through 2026-06-08 00:00 UTC.

All results below include an estimated round-trip cost:

- GBPUSD H1: `0.00012` price units, approximately 1.2 pips.
- XAUUSD H1: `0.50` price units, an initial proxy to replace with broker-specific spread/commission.

## GBPUSD H1 long

The best in-sample long row did not hold out-of-sample.

| Rank | Z long | ATR SL | R:R | Close break | IS trades | IS PF | IS Exp R | OOS trades | OOS PF | OOS Exp R | OOS Total R | OOS Max DD R |
| ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | -2.00 | 2.0 | 1.5 | true | 28 | 1.43 | 0.22 | 18 | 0.70 | -0.21 | -3.73 | 9.54 |
| 2 | -2.00 | 2.5 | 1.0 | true | 28 | 1.47 | 0.19 | 18 | 1.17 | 0.08 | 1.42 | 4.30 |
| 3 | -2.00 | 2.0 | 1.0 | true | 28 | 1.46 | 0.18 | 18 | 1.15 | 0.07 | 1.27 | 3.35 |
| 7 | -2.50 | 1.5 | 1.0 | true | 12 | 1.29 | 0.13 | 8 | 1.49 | 0.20 | 1.57 | 2.12 |

Read:

- Long is fragile on GBPUSD H1.
- The higher-win-rate 1.0R variants are more stable than 1.5R/2.0R.
- Trade count is limited, so this is not ready as a standalone long system.

## GBPUSD H1 short

GBPUSD H1 short is stronger than GBPUSD H1 long in this split.

| Rank | Z short | ATR SL | R:R | Close break | IS trades | IS PF | IS Exp R | OOS trades | OOS PF | OOS Exp R | OOS Total R | OOS Max DD R |
| ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1.75 | 2.5 | 2.0 | true | 37 | 1.31 | 0.19 | 28 | 1.24 | 0.15 | 4.14 | 6.16 |
| 5 | 1.75 | 2.5 | 2.0 | false | 61 | 1.17 | 0.11 | 40 | 1.03 | 0.02 | 0.78 | 13.37 |

Read:

- The top strict short candidate remains positive out-of-sample after cost assumptions.
- It has a lower win rate but a 2.0R target, so losing streaks remain meaningful.
- This is the best GBPUSD H1 candidate so far.

## XAUUSD H1 long

XAUUSD H1 long is the strongest candidate found in this cycle.

Data coverage:

- XAUUSD H1: 2021-01-03 23:00 UTC to 2026-06-08 00:00 UTC.

| Rank | Z long | ATR SL | R:R | Close break | IS trades | IS PF | IS Exp R | OOS trades | OOS PF | OOS Exp R | OOS Total R | OOS Max DD R |
| ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | -2.00 | 2.0 | 2.0 | false | 36 | 2.04 | 0.52 | 46 | 1.46 | 0.27 | 12.38 | 8.31 |
| 2 | -2.00 | 2.5 | 2.0 | false | 34 | 1.86 | 0.45 | 46 | 1.48 | 0.28 | 12.70 | 6.20 |
| 3 | -2.00 | 2.5 | 1.5 | false | 35 | 1.85 | 0.38 | 46 | 1.31 | 0.17 | 7.70 | 6.20 |
| 4 | -2.00 | 2.0 | 2.0 | true | 23 | 1.68 | 0.37 | 32 | 1.30 | 0.18 | 5.90 | 6.24 |

Read:

- Relaxing the close-break confirmation improves XAUUSD H1 long materially.
- The top two candidates survive out-of-sample after the initial cost proxy.
- Candidate 2 has slightly better OOS total R and lower OOS drawdown than candidate 1, at the cost of a wider stop.

## XAUUSD H1 short

XAUUSD H1 short is not robust in this split.

| Rank | Z short | ATR SL | R:R | Close break | IS trades | IS PF | IS Exp R | OOS trades | OOS PF | OOS Exp R | OOS Total R | OOS Max DD R |
| ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2.25 | 2.5 | 2.0 | true | 13 | 1.60 | 0.34 | 3 | 0.00 | -1.03 | -3.08 | 3.08 |
| 5 | 1.75 | 2.0 | 2.0 | false | 38 | 1.49 | 0.28 | 37 | 0.62 | -0.30 | -11.10 | 13.09 |

Read:

- Short looked good in-sample but failed out-of-sample.
- For GOLD, continue with long-only for the next research loop.

## Current candidates

1. `XAUUSD H1 long`, relaxed close-break:
   - RSI Z long <= -2.0.
   - ATR SL 2.0 or 2.5.
   - R:R 2.0.
   - `RequireCloseBreak = false`.

2. `GBPUSD H1 short`, strict close-break:
   - RSI Z short >= 1.75.
   - ATR SL 2.5.
   - R:R 2.0.
   - `RequireCloseBreak = true`.

## Next checks before paper/live

1. Re-run the candidates on the final broker MT5 Strategy Tester feed.
2. Replace proxy costs with exact broker spread/commission/slippage assumptions.
3. Add month/year breakdown to catch clustered performance.
4. Run Monte Carlo on trade sequences.
5. For XAUUSD, test session filters because liquidity/spread behavior changes strongly by hour.
