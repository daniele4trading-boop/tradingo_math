# Installazione EA su Moneta Funded (conto Instant 10k)

Guida pratica: solo **IVAN** e **STARK**, lotti Moneta, commenti `IT` / `AS`.

**Preset:** `tg_tradingo/mql5/presets/TG_TradinGo_Moneta_10k.set`  
**EA minimo:** v2.11 (lotti/tag per canale).

---

## Cosa fa questo preset

| Impostazione | Valore |
|--------------|--------|
| Canali ascoltati | `ivan,stark` (GOLD/ORO/FOREX spenti su questo MT5) |
| Lotto Ivan | **0.02** per ogni TP (segnale a 4 TP → 0.08 totali) |
| Lotto Stark | **0.01** |
| Commento Ivan | `IT-T1`, `IT-T2`, … (+ `signal_id` se presente) |
| Commento Stark | `AS-T1` |
| Kill-switch floating | 150 (nella **valuta del conto**) |
| Max holding | 90 minuti |
| Una sola istanza EA | sì |

Il bridge Contabo continua a scrivere **tutti** i JSON; su Moneta l’EA **ignora** i canali non in `InpChannels`.

---

## Architettura (una frase)

Contabo (bridge) → file `signal_ch_ivan.json` / `signal_ch_stark.json` → MT5 Moneta legge quei file (locale o via VPN) → apre trade sul conto Moneta.

---

## Passi su MT5 Moneta

### 1) Copia i file

1. Copia `TG_TradinGoEA.mq5` in  
   `File → Apri cartella dati → MQL5\Experts\`
2. Copia `TG_TradinGo_Moneta_10k.set` in  
   `MQL5\Presets\`
3. Assicurati che i JSON arrivino in `MQL5\Files\` (o `MQL5\Files\tradingo\`):
   - **Stessa VPS Contabo / stesso PC del bridge:** punta `signals_path` del bridge alla cartella Files di questo terminale, **oppure**
   - **VPS amico / VPN:** usa lo script `setup_friend_vps.ps1` (WriteShare) e sul Contabo aggiungi  
     `"signals_path": "\\\\10.8.0.X\\tradingo"`

### 2) Compila

1. Apri **MetaEditor** (F4 da MT5)
2. Apri `TG_TradinGoEA.mq5`
3. **F7** (Compile) — zero errori
4. In MT5, Navigator → Expert Advisors → aggiorna (tasto destro → Refresh)

### 3) Attacca l’EA

1. Apri un grafico **XAUUSD** (timeframe qualsiasi; **un solo grafico** con l’EA)
2. Trascina `TG_TradinGoEA` sul grafico
3. Scheda **Input** → **Load** → scegli `TG_TradinGo_Moneta_10k.set`
4. Controlla:
   - `InpChannels` = `ivan,stark`
   - `InpLotIvan` = `0.02`
   - `InpLotStark` = `0.01`
   - `InpTagIvan` = `IT`
   - `InpTagStark` = `AS`
   - `InpUseAbsolutePath` = false  
   - `InpSignalsPath` = vuoto **oppure** `tradingo\` se usi la junction VPN
5. Scheda **Comune**: spunta **Consenti trading automatico** / Allow Algo Trading
6. OK

### 4) Verifica

Nel tab **Esperti** deve comparire qualcosa come:

```
EA v2.11 started | channels=2
v2.11 lots/tags | ivan=0.02/IT stark=0.01/AS
```

Poi, al primo segnale Ivan: commento trade tipo `IT-T1-…`, lotto **0.02**.  
Stark: `AS-T1-…`, lotto **0.01**.

Pulsante **Algo Trading** in alto su MT5 deve essere **verde**.

---

## Contabo: cosa serve lato bridge

- Bridge **v2.06+** attivo (heartbeat + close intent)
- In `tradingo_config.json` → `mt5_instances`: una riga che scrive i JSON dove Moneta li legge
- **Non** serve disabilitare GOLD/ORO nel bridge se li vuoi ancora sul demo Vantage: basta che l’istanza Moneta abbia solo `InpChannels=ivan,stark`

Esempio istanza (path da adattare):

```json
{
  "name": "Moneta_10k",
  "enabled": true,
  "signals_path": "C:\\\\Users\\\\...\\\\MQL5\\\\Files\\\\tradingo"
}
```

oppure via VPN: `"\\\\10.8.0.2\\\\tradingo"`.

---

## Checklist sicurezza prop

- [ ] Un solo EA Moneta attivo (lock singolo)
- [ ] Solo canali Ivan + Stark
- [ ] Lotti 0.02 / 0.01
- [ ] Kill-switch floating ≤ 150 (o il valore che scegli sotto −200 Moneta)
- [ ] Demo / challenge test prima del funded se possibile
- [ ] Suffisso simbolo: se il broker usa `XAUUSD.m` ecc., imposta `InpSymbolSuffix`

---

## Problemi comuni

| Sintomo | Cosa controllare |
|---------|------------------|
| Nessun trade | Algo Trading off; JSON non aggiornati; canale non in `InpChannels` |
| Lotti sbagliati | Preset non caricato; EA &lt; v2.11; `InpLotIvan/Stark` a 0 |
| Commenti lunghi `TG-IVAN-…` | `InpCommentUseTgPrefix=true` o tag vuoti — usa il .set |
| Due EA sullo stesso conto | Lock: la seconda istanza non parte |
| FileOpen failed | Path JSON: prova `InpSignalsPath=tradingo\` e junction |
