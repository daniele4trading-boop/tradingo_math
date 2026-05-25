# TradinGO-Math manual trading - Fase demo

Questa fase introduce il pannello manuale e l'esecuzione MT5 controllata sui conti demo.

## Obiettivo

Spostare TradinGO-Math da sistema principalmente automatico a sistema guidato da dashboard:

1. l'utente inserisce una direzione hedge desiderata;
2. il sistema calcola la direzione prop speculare;
3. vengono suggeriti size, SL e TP per entrambi i conti;
4. il piano viene salvato in coda SQLite;
5. l'executor MT5 apre prima hedge e poi prop;
6. la Fase 2 continua a proteggere/ottimizzare le posizioni attive.

## Guardrail

- `execution_enabled` controlla se l'executor puo' chiamare `order_send`;
- l'executor apre prima Hedge e solo dopo Prop;
- gli ordini partono dalla coda `data/manual_orders.sqlite`;
- i motori live esistenti non vengono modificati;
- lo scanner setup resta separato e puo' essere disattivato/configurato in seguito.

Per i test demo attuali `execution_enabled` puo' essere `true`; per produzione deve tornare `false` finche' credenziali, tenant e risk policy non sono isolati.

## Direzioni

La dashboard chiede la direzione del conto hedge.

Esempio:

```text
Hedge BUY
Prop SELL
```

SL/TP sono speculari:

```text
Hedge BUY: SL sotto entry, TP sopra entry
Prop SELL: SL sopra entry, TP sotto entry
```

## Sizing

Il sizing prop e' calcolato dal rischio residuo disponibile:

```text
risk_budget = prop_balance * min(risk_per_trade, remaining_daily_dd, remaining_total_dd)
prop_lot = risk_budget / (sl_distance * contract_size)
hedge_lot = prop_lot * hedge_lot_multiplier
```

Per XAUUSD il `contract_size` di default e' `100`. Va verificato per ogni broker/simbolo prima dell'esecuzione reale.

## Executor

Il worker e':

```text
manual_trading.executor
```

Modalita':

```powershell
python -m manual_trading.executor --once
python -m manual_trading.executor --daemon
```

Funzioni:

- legge ordini `QUEUED` o `ARMED`;
- apre Hedge;
- se Hedge e' aperto correttamente, apre Prop;
- salva ticket e entry price;
- gestisce ordini `ACTIVE`;
- applica Fase 2;
- applica equity floor hedge.

## Hedge equity floor

Parametro:

```json
"hedge_equity_floor": 0.0
```

Se maggiore di zero, quando l'equity del terminale hedge e' minore o uguale al valore indicato, l'executor chiude le posizioni hedge.

Scope:

```json
"hedge_close_scope": "all"
```

Valori:

- `all`: chiude tutte le posizioni del conto hedge;
- `magic`: chiude solo le posizioni con `hedge_magic`.

## Fase 2

Parametro:

```json
"phase2_trigger_sl_fraction": 0.5
```

La Fase 2 si attiva quando il movimento rispetto all'entry prop raggiunge una frazione della distanza SL iniziale. Con `0.5`, si attiva al 50% della distanza SL.

Azioni Fase 2:

- Prop: SL portato a entry, TP rimosso;
- Hedge: SL protetto vicino a entry nel rispetto dello stop level broker, TP rimosso.

Ogni utente futuro dovra' avere tenant e worker isolati, non un unico processo condiviso.
