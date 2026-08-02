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
| Bridge Python | **2.14** | `BRIDGE_VERSION` in `tg_tradingo/tradingo_bridge.py` (banner di avvio e `start_tradingo.bat`) |
| EA MT5 | **2.14** | `#property version` + `#define EA_VERSION` in `tg_tradingo/mql5/TG_TradinGoEA.mq5` |

Le due versioni si muovono insieme: bridge ed EA condividono il contratto JSON descritto in
[`EA_SPEC.md`](EA_SPEC.md), quindi un cambio di contratto va rilasciato su entrambi.
Nell'EA tutti i `Print("[TradinGo] v…")` usano `EA_VERSION`: non esistono più versioni
scritte a mano nei log.

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

Dettaglio delle regole iFunds e procedure di test dei guard: [`IFUNDS_SETUP.md`](IFUNDS_SETUP.md).

## Cosa gira in produzione

| Macchina | Componente | Preset |
|---|---|---|
| Contabo `144.91.76.28` | bridge Python + terminale Vantage demo | `TG_TradinGo_Vantage_Demo.set` |
| Gamehosting `100.74.9.8` | terminale Ultima demo | `TG_TradinGo_Ultima_iFunds_Demo.set` |

Il deploy non è automatico: `C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1` per il bridge,
copia manuale del `.mq5` + compilazione in MetaEditor per l'EA.
