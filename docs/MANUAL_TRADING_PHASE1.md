# TradinGO-Math manual trading - Fase 1

Questa fase introduce il pannello manuale senza inviare ancora ordini reali a MT5.

## Obiettivo

Spostare TradinGO-Math da sistema principalmente automatico a sistema guidato da dashboard:

1. l'utente inserisce una direzione hedge desiderata;
2. il sistema calcola la direzione prop speculare;
3. vengono suggeriti size, SL e TP per entrambi i conti;
4. il piano viene salvato in coda SQLite;
5. nella fase successiva un worker MT5 dedicato eseguira' solo piani confermati.

## Stato sicurezza

In Fase 1:

- `execution_enabled = false`;
- nessun `order_send` viene chiamato dal nuovo modulo;
- gli ordini sono solo `QUEUED` in `data/manual_orders.sqlite`;
- i motori live esistenti non vengono modificati;
- lo scanner setup resta separato e puo' essere disattivato/configurato in seguito.

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

## Prossimo collegamento ai worker

La fase successiva aggiungera':

- worker `manual_executor` separato dai motori scanner;
- lettura della coda `QUEUED`;
- doppia conferma dashboard;
- invio prima su hedge, poi su prop;
- salvataggio ticket MT5;
- gestione Fase 2/piramidazione/protezione profitti.

Ogni utente futuro dovra' avere tenant e worker isolati, non un unico processo condiviso.
