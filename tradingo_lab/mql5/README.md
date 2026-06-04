# TradinGo MQL5 Expert Advisors

## EA

`Experts/TradinGo/TradinGo_ICT_QualityFailed_XAUUSD.mq5`

Research/test EA for XAUUSD M1 based on the combined ICT setup found in `tradingo_lab`:

- quality ICT reversal in NY Open;
- failed-reversal continuation in high-volatility/overextended conditions;
- configurable spread filter, default `InpMaxSpreadPoints=25`;
- demo/tester protection enabled by default via `InpRequireDemoAccount=true`;
- risk-percent sizing enabled by default at `InpRiskPercent=1.0`;
- time exit after the configured horizon bars if neither SL nor TP is hit.

## Default strategy mode

`InpStrategyMode=TG_QUALITY_PLUS_FAILED`

This trades:

1. quality reversal when `ATR <= 279` and directional previous-10-minute move is not too extended;
2. failed-reversal continuation when `ATR >= 450` and directional previous-10-minute move is overextended.

Other strategy modes are available in the EA inputs:

- `TG_CORE_WITH_FAILED_REPLACEMENT`
- `TG_QUALITY_ONLY`
- `TG_FAILED_ONLY`
- `TG_CORE_ONLY`

## Installation

Copy the EA to the target terminal data folder, for example:

```powershell
copy mql5\Experts\TradinGo\TradinGo_ICT_QualityFailed_XAUUSD.mq5 "$env:APPDATA\MetaQuotes\Terminal\<TERMINAL_ID>\MQL5\Experts\TradinGo\"
copy mql5\Presets\TradinGo_ICT_QualityFailed_XAUUSD_spread25.set "$env:APPDATA\MetaQuotes\Terminal\<TERMINAL_ID>\MQL5\Profiles\Tester\"
```

Then compile in MetaEditor and run Strategy Tester on:

- symbol: `XAUUSD`
- timeframe: `M1`
- initial deposit: `50000`
- model: real ticks if available, otherwise every tick based on real ticks.

## Safety

The EA is intended for backtest/demo validation. With default settings it blocks trading on real accounts.
