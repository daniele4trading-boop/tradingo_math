# Scalping — Ottimizzazione Frequenza (Fase 1)

Obiettivo: massimizzare numero trade su train Mar–Apr, validazione full sample.

Fase 2 (affinamento expectancy/PF) da fare successivamente.

| Profilo | Train trades | Full trades | Full exp | Full PF | Win% | Max DD | PnL |
|---------|-------------|-------------|----------|---------|------|--------|-----|
| **H1_M5** | 61 | 96 | -0.70R | 0.13 | 12.5% | -67.4% | -6746 |
| **M15_M5** | 96 | 180 | -0.52R | 0.27 | 17.2% | -94.4% | -9318 |

### H1_M5
```json
{
  "sweep_atr_mult": 0.25,
  "equal_highs_tolerance_atr": 0.8,
  "min_rr": 1.5,
  "limit_expire_bars_m5": 18,
  "impulsive_body_ratio": 0.5,
  "max_setup_age_bars": 18,
  "sl_atr_buffer_mult": 0.25,
  "cooldown_bars_m5": 6,
  "h4_supply_pct": 0.95,
  "context_filter": true,
  "liquidity_lookback_bars": 80
}
```

### M15_M5
```json
{
  "sweep_atr_mult": 0.15,
  "equal_highs_tolerance_atr": 0.8,
  "min_rr": 1.0,
  "limit_expire_bars_m5": 30,
  "impulsive_body_ratio": 0.45,
  "max_setup_age_bars": 18,
  "sl_atr_buffer_mult": 0.3,
  "cooldown_bars_m5": 3,
  "h4_supply_pct": 0.95,
  "context_filter": false,
  "liquidity_lookback_bars": 120
}
```