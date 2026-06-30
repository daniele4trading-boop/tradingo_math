# StatArb — Checklist lunedì mattina (prima sessione demo)

VPS: `144.91.76.28` · Path: `C:\StatArb` · Porta UI: `8520`

---

## 1. Prima di aprire il mercato (≈ 30 min)

- [ ] **RDP sulla VPS** e apri **3 terminali MT5** già loggati su demo:
  - XM (data source — opzionale se usi solo cache)
  - **Ultima Markets** (leg A)
  - **Vantage** (leg B)
- [ ] Verifica **IP VPS** ancora whitelisted sui broker (se richiesto).
- [ ] In PowerShell:
  ```bat
  cd C:\StatArb
  python preflight.py
  ```
  Atteso: **FAIL=0** (WARN su processi Python ok).
- [ ] Aggiorna cache dati (mercato aperto):
  ```bat
  python tests\test_module2_scanner.py
  ```
  Atteso: **20/20 OK** (o almeno coppie operative senza errori).

---

## 2. Verifica segnali e risk (mercato aperto)

- [ ] Engine + selezione:
  ```bat
  python tests\test_module3_engine.py
  ```
- [ ] Risk live:
  ```bat
  python tests\test_module5_risk.py
  ```
- [ ] Piano senza ordini:
  ```bat
  python launch\cli.py --no-execute
  ```
  Controlla tabella **Action plan** — azioni `OPEN` / `CLOSE` sensate.

---

## 3. Avvio monitoraggio

- [ ] UI dashboard (solo sulla VPS via RDP):
  ```bat
  C:\StatArb\run_ui.bat
  ```
  Browser sulla VPS: **http://127.0.0.1:8520**
- [ ] UI da **cellulare / PC esterno** (stessa rete o internet, se firewall ok):
  ```bat
  C:\StatArb\run_ui_public.bat
  ```
  URL: **http://144.91.76.28:8520** (IP VPS + porta 8520)
  - Streamlit deve essere in ascolto su `0.0.0.0` (non `127.0.0.1`)
  - Se non risponde: apri porta **8520** in Windows Firewall (inbound)
- [ ] Sidebar: **MT5 live ON** → verifica equity Ultima + Vantage
- [ ] Sezione **Backtest** in UI: ultimi `backtest.lookback_days` giorni (default 90) su cache

---

## 4. Primo ciclo operativo (dry-run)

Con `params.json` → `execution.dry_run: **true**` (default attuale):

```bat
cd C:\StatArb
python launch\cli.py --refresh
```

- [ ] Report: `state\launch\last_cycle.json`
- [ ] Log: `state\statarb_logs\statarb_launch.log`
- [ ] Atteso: `order_check` OK su coppie con `action=OPEN`, **nessun ordine reale**.

---

## 5. Primo ordine reale micro (solo se dry-run OK)

1. Backup `params.json`.
2. Imposta `execution.dry_run: false`.
3. Verifica `max_executions_per_cycle: 1` in `launch`.
4. Un solo ciclo:
   ```bat
   python launch\cli.py
   ```
5. Controlla posizioni su **entrambi** i broker (magic `30_260_xxx`).
6. Se tutto ok, valuta `run_statarb_loop.bat` (ciclo ogni 15 min).

**Rollback:** ripristina `dry_run: true` e chiudi hedge manualmente o via script se necessario.

---

## 6. Coppie prioritarie (da backtest Modulo 7)

| Priorità | Coppia | Nota |
|----------|--------|------|
| Alta | XPTUSD/XPDUSD | Backtest net positivo |
| Alta | XAUUSD/XPTUSD | Backtest net positivo |
| Media | GER40/EU50 | Segnale frequente; verificare live |
| Bassa | US500/NAS100 | Molti trade, net negativo in backtest |
| Evitare | AUDUSD/NZDUSD | Non selezionata, backtest molto negativo |

---

## 7. Limiti risk attivi (`params.json`)

| Parametro | Valore |
|-----------|--------|
| max_concurrent_pairs | 8 |
| max_pairs_sharing_leg | 1 |
| daily_loss / account | 4% |
| max_drawdown | 8% |
| margin_floor | 200% |
| risk_per_trade | 0.5% |

---

## 8. Se qualcosa va storto

| Problema | Azione |
|----------|--------|
| MT5 authorization failed | Chiudi terminali, riapri, rilancia |
| UI non si apre | `diagnose_ui.bat` poi `run_ui.bat` |
| Unhedged (una gamba sola) | **Stop nuovi OPEN** — chiudi gamba orfana |
| Risk gate blocca tutto | Leggi `module5` / `last_cycle.json` warnings |
| Simbolo ambiguo | Aggiorna `accounts.json` symbol_map |

---

## 9. Comandi rapidi

```bat
cd C:\StatArb
python preflight.py
python launch\cli.py --refresh --no-execute
python launch\cli.py --refresh
run_ui.bat
run_statarb_loop.bat
```

---

## 10. Cursor Remote SSH (agente su VPS)

- [ ] Sulla VPS, **come Amministratore**:
  ```bat
  C:\StatArb\scripts\add_cursor_ssh_key.bat
  ```
- [ ] Firewall porta **2222**:
  ```bat
  netsh advfirewall firewall add rule name="OpenSSH 2222" dir=in action=allow protocol=TCP localport=2222
  ```
- [ ] Sul tuo PC Cursor: SSH config → `Host statarb-vps` · `HostName 144.91.76.28` · `User Administrator` · `Port 2222`
- [ ] Dettagli: `C:\StatArb\CURSOR_SSH_SETUP.md`

---

*Generato dopo accettazione Moduli 0–8 — profilo selezione **test** (9/10 coppie). Per produzione: stringere filtri in `params.json` e usare backtest per scartare coppie deboli.*
