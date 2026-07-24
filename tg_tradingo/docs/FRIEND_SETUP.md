# Setup TG TradinGo per amici (solo EA)

Guida per installare l'EA su una VPS/PC separata e ricevere i segnali JSON dal bridge principale.

**Test VPN Contabo ↔ VPS amico (path JSON remoti, latenza):** vedi [`FRIEND_VPN_SETUP.md`](FRIEND_VPN_SETUP.md).

## Cosa serve

- MetaTrader 5 (conto demo o live del broker dell'amico)
- File `TG_TradinGoEA.mq5` da `tg_tradingo/mql5/`
- Accesso ai file `signal_ch_*.json` (sync o share di rete)

**Non serve** Python, Telegram o il bridge sull'host dell'amico.

## Installazione EA

1. Copia `TG_TradinGoEA.mq5` in `MQL5\Experts\` del terminale MT5.
2. In MetaEditor: **Compile** (F7).
3. In MT5: trascina l'EA su un chart qualsiasi (simbolo irrilevante).
4. Abilita **AutoTrading**.

### Parametri consigliati

| Parametro | Valore tipico |
|-----------|---------------|
| `InpSignalsPath` | `C:\TG_TradinGo\signals\` oppure cartella sync |
| `InpUseAbsolutePath` | `true` se path assoluto Windows |
| `InpChannels` | `gold,forex,oro,stark` (solo le sale che vuoi copiare) |
| `InpSymbolSuffix` | suffisso broker se serve (es. `m`) |
| `InpLotMultiplier` | `1.0` (o meno per ridurre rischio) |

## Come arrivano i segnali JSON

### Opzione A — Bridge centrale (consigliata)

Sul server dove gira `tradingo_bridge.py`, aggiungi in `tradingo_config.json`:

```json
{
  "name": "Amico_Mario",
  "enabled": true,
  "signals_path": "\\\\IP_AMICO\\TG_TradinGo\\signals"
}
```

Oppure il path locale `MQL5\Files` dell'amico se montato come share:

```json
"signals_path": "C:\\Users\\Mario\\AppData\\Roaming\\MetaQuotes\\Terminal\\HASH\\MQL5\\Files\\tradingo"
```

L'amico imposta `InpSignalsPath` sulla stessa cartella e `InpUseAbsolutePath=true`.

### Opzione B — Sync manuale / script

Copia periodicamente da `C:\TG_TradinGo\signals\` del server i file:

- `signal_ch_gold.json`
- `signal_ch_forex.json`
- `signal_ch_oro.json`
- `signal_ch_stark.json`

### Opzione C — Solo MQL5\Files

Configura il bridge per scrivere direttamente in:

```
%APPDATA%\MetaQuotes\Terminal\<HASH>\MQL5\Files\tradingo\
```

L'amico usa:

- `InpUseAbsolutePath = false`
- `InpSignalsPath = tradingo\` (path relativo a MQL5\Files)

## Verifica

1. Controlla che i JSON si aggiornino (campo `timestamp` cambia).
2. Tab **Experts** in MT5: log `[TradinGo] signal_ch_*.json action=OPEN ...`
3. Su conto **demo** prima di live.

## Magic numbers

L'EA usa `magic_base` dal JSON + indice trade. Non sovrapporre altri EA con gli stessi magic sulla stessa coppia.

| Canale | Magic tipici |
|--------|----------------|
| GOLD | 12001, 12002 |
| FOREX | 13001 |
| ORO | 14101, 14102 |
| STARK | 14001 |

## Risoluzione problemi

| Problema | Soluzione |
|----------|-----------|
| `FileOpen failed` | Path errato; prova `InpUseAbsolutePath=false` e file in MQL5\Files |
| Nessun trade | `AutoTrading` disabilitato o simbolo non nel Market Watch |
| Simbolo non trovato | Imposta `InpSymbolSuffix` (es. `m` per XAUUSDm) |
| Lotti troppo grandi | Riduci `InpLotMultiplier` |

Specifica completa: [`EA_SPEC.md`](EA_SPEC.md)
