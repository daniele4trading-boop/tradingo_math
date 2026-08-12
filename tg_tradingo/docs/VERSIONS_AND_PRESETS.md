# Versioni correnti e mappa preset → conto

Documento di riferimento rapido per chi riprende il lavoro (Cursor Cloud, agenti, deploy manuale).

## Branch canonico

Il branch di lavoro è **`main`**: contiene bridge, EA, preset, webapp, docs, test e script di deploy.

```bash
git fetch origin main && git checkout main && git pull
```

I branch `cursor/*` e `devin/*` sono di lavoro: allinearli a `main` prima di ripartire.

## Versioni

| Componente | Versione | Dove è dichiarata |
|---|---|---|
| Bridge Python | **2.18** | `BRIDGE_VERSION` in `tg_tradingo/tradingo_bridge.py` (banner di avvio e `start_tradingo.bat`) |
| EA MT5 | **2.19** | `#property version` + `#define EA_VERSION` in `tg_tradingo/mql5/TG_TradinGoEA.mq5` |
| EA MT4 | **1.06** | `#property version` + `#define EA_VERSION` in `tg_tradingo/mql4/TG_TradinGoEA.mq4` (stesso contratto JSON del bridge 2.18) |

Bridge ed EA MT5 si muovono insieme sul contratto JSON ([`EA_SPEC.md`](EA_SPEC.md)).
L’EA MT4 è un consumer aggiuntivo dello stesso JSON (nessun secondo parser).
Setup Contabo T4Trade + predisposizione path iFunds: [`MT4_T4TRADE_SETUP.md`](MT4_T4TRADE_SETUP.md).

**2.18 / MT5 2.19 / MT4 1.06:** parser GOLD — il canale a volte ripubblica lo stesso
setup tradotto ("Gold on sale now", "Oro a la venta ahora", "Precio actual del oro",
"COMPRAR/VENTA XAUUSD") o scrive `Typ:` per `Tp:`, e decora i livelli con emoji
("ZONA ➡️ 4425 - 4422"): tutte queste forme ora emettono il setup, con `entry_range`
popolato anche dietro le label `ZONE/ZONA/PRECIO ACTUAL`. Quando il testo tradotto perde
la direzione, questa si ricava dalla posizione di SL e TP rispetto alla zona. Parser IVAN —
un'entry incoerente ma con SL e TP coerenti fra loro (`XAUUSD SELL 4326` con SL 4436 e TP
4420→4408, entry vera ~4427) non fa più scartare il segnale: si apre a mercato
(`entry=null`, log `ENTRY_TYPO_MARKET`). Lato EA nuovo `InpProtectExistingLevels`
(default true): quando un setup nuovo arriva con posizioni aperte e `allow_stack=false`,
l'EA ne modifica SL/TP ma non applica più un TP dal lato in perdita rispetto al prezzo di
apertura della posizione (`MODIFY_SKIPPED_ADVERSE_TP`) né uno SL già superato dal mercato
(`MODIFY_SKIPPED_CROSSED_SL`), che il 12/08 avevano chiuso un BUY GOLD a -86,77.

**2.17 / MT5 2.18 / MT4 1.05:** parser IVAN — i desiderativi ("vorrei rientrare",
"volevo rientrare", "mi piacerebbe rientrare") non aprono più il rientro, e i consuntivi
con verbo di chiusura ("E anche oggi chiudiamo in Profitto", "chiudiamo la settimana")
non emettono più `CLOSE_ALL_SYMBOL` — i comandi espliciti (`CHIUDIAMO ORA`, `USCIAMO`,
`chiudiamo tutto`) restano validi. Lato EA nuovo `InpReentryMaxDriftPctOfSl` (default 40):
un rientro eredita lo SL del setup originale, quindi se il mercato si è già mangiato più
di quella quota della distanza entry→SL il rientro viene scartato
(`REENTRY_CANCELLED`, stat `CANCELLED_REENTRY_DRIFT`). 0 = guard disattivato.

**MT5 2.17:** `InpDdRecoveryLot` — sotto la soglia `InpDdBlockNewAtPct` l'EA non blocca
più tutte le aperture: se l'input è > 0 continua a eseguire i segnali a quel lotto
(0,01 sui preset iFunds) finché l'equity non risale sopra la soglia. Bridge ed EA MT4
invariati (il guard DD esiste solo su MT5).

**2.16 / MT4 1.04:** parser IVAN — gli annunci condizionali di rientro ("se ritraccia
rientriamo", "zona reentry 56-53") non aprono più, "chiudo la rientry" emette
`CLOSE_SELECTIVE keep=ALL_BUT_NEWEST` (chiude solo l'ultimo blocco), "spostiamo lo stop a X"
emette `UPDATE_SL`; lato EA nuovo guard `InpMaxLevelDeviationPct` (scarta i segnali con
livelli fuori scala rispetto al prezzo) e `InpBatchWindowSec`.

**2.15 / MT4 1.03:** `OPEN_NOW` apre subito `tp_levels_expected` ticket (GOLD=2×`fixed_lot_per_tp`); `UPDATE_OPEN` fa fill per-magic senza close/reopen.

Contenuto della 2.14 rispetto alla 2.10 del bridge: parser post-audit (PR #21-#28) —
forme italiane GOLD/FOREX, dedup MSG+EDIT, chiusure selettive `CLOSE_SELECTIVE`,
rientri IVAN con filtro anti-frase-di-attesa — e lato EA guard DD statico su equity,
kill switch manuale, sizing dal serbatoio, cap sui lotti concorrenti, cooldown killswitch a 0.

## Preset → conto

Tutti in `tg_tradingo/mql5/presets/`, si caricano da `Inputs → Load` sul chart dell'EA.

| Preset | Conto | Guard DD | Sizing serbatoio | Canali | Note |
|---|---|---|---|---|---|
| `TG_TradinGo_Vantage_Demo.set` | Vantage demo (Contabo) | off | off | tutti e 5 | conto "misura i canali": nessun guard altera i risultati |
| `TG_TradinGo_Ultima_iFunds_Demo.set` | Ultima demo (Gamehosting) | 6%, start 10.000 → floor 9.400 | on, cap 0,05 | ivan, stark | prova delle regole iFunds; `InpMagicOffset=0` per non perdere le posizioni già aperte |
| `TG_TradinGo_iFunds_10k_dd6.set` | iFunds 10k reale | 6%, start 10.000 → floor 9.400 | on, cap 0,05 | ivan, stark | `InpMagicOffset=500000` |
| `TG_TradinGo_iFunds_50k_dd6.set` | iFunds 50k reale | 6%, start 50.000 → floor 47.000 | on, cap 0,25 | ivan, stark | scalata dopo il 10k |
| `TG_TradinGo_Reale_Personale.set` | conti reali personali | 10%, equity catturata al primo attach | off | ivan, stark (da scegliere) | template: lotti, suffisso simbolo e % vanno adattati al broker |
| `TG_TradinGo_Moneta_10k.set` | Moneta Funded 10k | off | off | ivan, stark | storico: piano abbandonato, lotti fissi 0,02/0,01 |
| `TG_TradinGo_Gamehosting_Demo.set` | demo su VPS amico | off | off | tutti e 5 | usa la junction `MQL5\Files\tradingo` |

Preset MT4 in `tg_tradingo/mql4/presets/`:

| Preset | Conto | Canali | Note |
|---|---|---|---|
| `TG_TradinGo_T4Trade_Reale.set` | T4Trade reale (Contabo) | tutti e 5 (editabili) | lotti 0.01; path `MQL4\Files\tradingo\` |

Dettaglio delle regole iFunds e procedure di test dei guard: [`IFUNDS_SETUP.md`](IFUNDS_SETUP.md).

## Cosa gira in produzione

| Macchina | Componente | Preset |
|---|---|---|
| Contabo `144.91.76.28` | bridge Python + terminale Vantage demo | `TG_TradinGo_Vantage_Demo.set` |
| Gamehosting `100.74.9.8` | terminale Ultima demo | `TG_TradinGo_Ultima_iFunds_Demo.set` |

Il deploy non è automatico: `C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1` per il bridge,
copia manuale del `.mq5` + compilazione in MetaEditor per l'EA.
