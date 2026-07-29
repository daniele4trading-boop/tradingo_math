# Audit parser Telegram → JSON (luglio 2026)

Audit di precisione dei soli parser (`tradingo_bridge.py`) + stato canale
(`bridge_core.BridgeState`). Nessuna modifica a scrittura JSON, EA, rete o
infrastruttura.

Strumento di replay offline: [`parser_dryrun.py`](../parser_dryrun.py) — rigioca i
messaggi mantenendo lo stato canale (CH2 naked→UPDATE, ORO pending, FOREX pending,
GOLD/STARK last trade) in un `EphemeralBridgeState` in memoria: nessun file di
segnale o di stato viene scritto.

```bash
# dump del sampler (fixture in repo o logs/signals_*.txt del VPS)
python parser_dryrun.py --dump docs/fixtures/signal_samples.txt
python parser_dryrun.py --dump docs/fixtures/signals_apr21.txt --channel CH2

# journal di produzione: confronta l'esito registrato con quello ricalcolato
python parser_dryrun.py --events journal/bridge_events/events_20260724.jsonl --diff
```

## Casistiche corrette in questo audit

| Canale | Messaggio esempio | Action attesa | Action prima | Priorità |
|---|---|---|---|---|
| CH1 zanni | `E sposto stop a BE` | `CHECK_AND_BE` | UNPARSED (BE non riconosciuto) | alta |
| CH1 zanni | `Portiamo lo stop loss in pareggio` | `CHECK_AND_BE` | UNPARSED | alta |
| CH1 zanni | `…chiudete il tp1 anche a 4817!` | `CHECK_AND_CLOSE_TP` (tp 1) | UNPARSED (`CHIUD[OI]` non copriva `CHIUDETE`) | alta |
| CH2 gold | `+70 pips close half break even close` | `CLOSE_HALF_BE` | `CLOSE_ALL_SYMBOL` (il `close` finale vinceva) | **critica** |
| CH2 gold | `SL 4807` dopo un setup GOLD | `UPDATE_SL` | UNPARSED (SL spostato ignorato) | alta |
| CH2 gold | `SL 4807` senza trade noto / SL uguale | ignorato | UNPARSED (identico esito, ora esplicito) | bassa |
| CH2 gold | ri-invio identico dello stesso setup entro 30′ | ignorato | secondo `OPEN` (stack sull'EA) | **critica** |
| CH3 forex | `NUOVO ORDINE - GBPCADpm Buy … Questo messaggio non incita a investire` | pending, poi `OPEN` col `Modificato` | UNPARSED: il disclaimer faceva scattare l'ignore, nessun `OPEN` | **critica** |
| CH3 forex | `CHIUSO - GBPUSDpm Sell … Questo messaggio non incita…` | `CHECK_AND_CLOSE` | UNPARSED (stesso motivo) | **critica** |
| CH4 stark | `Chiusa in take profit ✅` / `Chiusa a Break Even **XAUUSD**` | `CLOSE_ALL_SYMBOL` | UNPARSED (chiusura manuale del canale non replicata) | alta |
| CH4 stark | `Chiusa …` senza simbolo né trade noto | ignorato | UNPARSED | bassa |
| CH_ORO | `Chiudiamo tutto ragazzi` | `CLOSE_ALL_SYMBOL` | UNPARSED (`RAGAZZI` bloccava la chiusura) | **critica** |
| CH_ORO | `usciamo qui a 4015` | `CLOSE_ALL_SYMBOL` + `reference_price` | UNPARSED (nessun recognizer di uscita su ORO) | **critica** |
| CH_ORO | `Attendiamo XAUUSD BUY 4050 \| TP 4060 \| SL 4040` | `OPEN` | UNPARSED (`ATTENDIAMO` bloccava il setup) | alta |
| CH_ORO | `Ragazzi stasera live di formazione`, `Report: +300 pips ✅` | ignorato | ignorato (invariato) | — |
| CH_IVAN | setup completo che contiene anche `Take profit ravvicinati` | `OPEN` | ignorato (`TAKE PROFIT` copriva il segnale) | alta |
| CH_IVAN | `Pronti a chiudere se ve lo dico` | ignorato | ignorato (invariato) | — |

## Cosa è cambiato nei parser

- **Registry ignore centralizzato** (`IGNORE_PATTERNS` + `matched_ignore_pattern`):
  gli stessi pattern servono sia il parser sia la classificazione
  `IGNORED_PATTERN` nel journal (prima il journal conosceva solo 4 pattern IVAN,
  quindi tutto il resto finiva `UNPARSED`). Corretto anche `FORMazione` (mai
  matchato, il testo è già upper) e `LIVE` → `\bLIVE\b` (matchava `LIVELLO`).
- **Gli ignore non coprono più un messaggio operativo**: GOLD/IVAN li applicano
  solo se il testo non è un setup completo; FOREX solo se non c'è un blocco
  `NUOVO ORDINE` / `Modificato` / `CHIUSO`; ORO solo se non ci sono direzione,
  livelli o intento di chiusura.
- **CH2 GOLD**: `CLOSE_HALF_BE` valutato prima della chiusura totale; `SL <px>`
  standalone → `UPDATE_SL`; nuovo stato `gold_last_trade` (direzione/entry/SL/TP
  + timestamp) usato per riconoscere il ri-invio identico entro
  `GOLD_REPOST_TTL_SEC` (30′) ed evitare lo stack di un secondo `OPEN`.
  Il flusso `OPEN_NOW → UPDATE_OPEN` resta invariato.
- **CH_ORO**: aggiunto il recognizer di chiusura totale condiviso
  (`_maybe_close_from_text`), che azzera pending e last trade.
- **CH4 STARK**: riconosce `Chiusa a/in …` come `CLOSE_ALL_SYMBOL`, con simbolo
  preso dal testo o dal nuovo stato `stark_last_trade`; se non c'è nessuno dei
  due il messaggio resta ignorato (nessuna chiusura “a indovinare”).

Nessun campo JSON nuovo verso l'EA: `UPDATE_SL` e `CLOSE_ALL_SYMBOL` erano già
nel contratto (`docs/EA_SPEC.md`). `bridge_core.py` cambia solo per i due nuovi
campi di stato interno (`gold_last_trade`, `stark_last_trade`) in
`state/bridge_state.json`.

## Gap noti ancora aperti (nessuna azione emessa, volutamente)

| Canale | Casistica | Perché resta così |
|---|---|---|
| CH4 stark | `Take Profit 1 preso`, `Stop Loss preso`, `Sposto lo Stop Loss a Break Even` | BE/TP sono gestiti dall'EA sui nostri livelli; replicarli manualmente chiuderebbe posizioni valide |
| CH4 stark | `SELL EURUSD 1.17086 / SL 1.14500 / TP 1.17180` (geometria incoerente) | scartato da `validate_signal`: la direzione corretta non è deducibile senza ambiguità |
| CH1 zanni | chatter promozionale (`STIAMO VOLANDO`, screenshot profitti) | nessuna azione operativa; classificato `UNPARSED` (nessun pattern ignore registrato per CH1) |
| CH3 forex | `NUOVO ORDINE` senza `Modificato` successivo | per contratto l'`OPEN` richiede TP: resta pending fino al messaggio di modifica |

## Limite dell'audit

Il replay è stato eseguito sulle fixture in repo (`docs/fixtures/signal_samples.txt`,
`signals_apr21.txt`, `docs/fixtures/journal_sample/`). **Non** è stato possibile
usare i mesi di storico di produzione (`C:\TG_TradinGo\logs\`,
`journal\bridge_events\`, `trades_*.csv`, `tradingo_signal_stats.csv`): manca
l'accesso al VPS. Per completare il confronto “segnale emesso vs eseguito”:

```powershell
# sul VPS, senza fermare il bridge (sola lettura)
cd C:\TG_TradinGo
python fetch_date_range.py --from 2026-04-01 --to 2026-07-28 --parser-dry-run
python parser_dryrun.py --events journal\bridge_events\events_20260724.jsonl --diff
python parser_dryrun.py --dump logs\signals_20260401_20260728.txt --only-unparsed
```

`--diff` elenca solo i messaggi il cui esito cambia con i parser correnti: è la
lista da validare prima del deploy.
