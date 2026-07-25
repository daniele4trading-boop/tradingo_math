# Journal specification (TG TradinGo)

Artefacts that link Telegram → bridge → MT5 positions for offline analysis.
Introduced with bridge **v2.06** / EA **v2.10**.

## Roots

| Writer | Default path |
|--------|----------------|
| Bridge | `C:\TG_TradinGo\journal\` (`paths.journal` in config, optional) |
| EA | `MQL5\Files\journal\` (`InpJournalPrefix`) |

Runtime journals are **not** git-tracked. Sample fixtures: `docs/fixtures/journal_sample/`.

Retention / compression: keep last **90** days (configurable later); deploy scripts must not wipe journals.

---

## Artefact A — Bridge events (JSONL)

Path: `journal/bridge_events/events_YYYYMMDD.jsonl`  
One line per Telegram event processed (including non-emitted).

| Field | Notes |
|-------|--------|
| `ts_utc` | Reception time |
| `channel_id`, `chat_id`, `message_id`, `event_type` | `NEW` / `EDIT` |
| `raw_text` | Full text |
| `outcome` | `EMITTED` · `IGNORED_PATTERN` · `UNPARSED` · `PARSE_ERROR` · `DUPLICATE` |
| `matched_pattern` | Ignore regex if `IGNORED_PATTERN` |
| `error` | Compact error if `PARSE_ERROR` |
| `signal_id` | If `EMITTED` |
| `action`, `payload`, `targets` | Emitted action / JSON / written paths |

---

## Artefact B — Trade journal (CSV)

Path: `journal/trades/trades_YYYYMMDD.csv` (EA)  
One logical position lifecycle (OPEN row + CLOSE row, or single completed row depending on EA build).

Key columns: `signal_id`, `channel`, `tp_index`, `ticket`, `magic`, `symbol`, `direction`,
request levels, fill/slippage, account snapshot at open, MAE/MFE, close fields.

`close_reason` enum:

`TP` · `SL` · `BE_SL` · `CLOSE_ALL_SIGNAL` · `CLOSE_HALF` · `KILLSWITCH_FLOATING` ·
`KILLSWITCH_TIME` · `MANUAL` · `UNKNOWN`

`tradingo_signal_stats.csv` remains until the trade journal is validated ≥1 week.

---

## Artefact C — Market context (JSON)

Path: `journal/context/ctx_{signal_id}.json`  
Written when the first TP leg of a `signal_id` opens.

Raw only: M1/M15/H1 bars, spread, ATR, day levels, session name, distances in points.
**No** setup labels or narrative.

---

## Artefact D — Equity samples (CSV)

Path: `journal/equity/equity_YYYYMMDD.csv`  
Interval: `InpEquitySampleSec` (default 60).

`ts_utc,balance,equity,floating_total,floating_per_symbol_bucket,open_positions_count,total_lots,margin_used,margin_level`

---

## Artefact E — Analysis script

`tg_tradingo/analyze_journal.py` — offline join of A–D (+ optional news calendar).

```bash
python analyze_journal.py \
  --journal-root docs/fixtures/journal_sample \
  --from 2026-07-24 --to 2026-07-24 \
  --news-calendar docs/fixtures/news_calendar.csv \
  --lot-mult ivan=0.2 --lot-mult stark=0.05
```

Outputs JSON: per-channel stats, distributions, prop curves, lot simulator, parser coverage, news window counts.
News labeling only — **no** operational news block in this version.

---

## `signal_id`

Deterministic `sha256(chat_id:message_id:event_type)[:10]`.  
Present in bridge JSON, EA comments (`TG-{CH}-T{n}-{signal_id}`, ≤31 chars), and all artefacts.
Comment is convenience; **ticket + trade journal** is source of truth.
