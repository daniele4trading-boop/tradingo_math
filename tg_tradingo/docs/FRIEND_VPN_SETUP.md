# VPN amico (gamehosting) → JSON su Contabo

Obiettivo: ogni amico ha **MT5 + EA sulla propria VPS**, legge i JSON prodotti dal bridge sulla **VPS Contabo** (attuale), con latenza bassa e misurabile.

```
[Contabo] tradingo_bridge.py
    → scrive C:\TG_TradinGo\signals\signal_ch_*.json
    → (opzionale) share SMB solo su rete VPN

[WireGuard]
    Contabo 10.8.0.1  ←→  Amico 10.8.0.2

[gamehosting] MT5 + TG_TradinGoEA
    → legge i JSON (via share montata in MQL5\Files)
```

Porta `185.229.236.83:27842` = tipicamente **RDP**, non serve per i JSON.  
Serve: **WireGuard UDP** + **SMB** (o copia locale della share).

---

## Architettura consigliata per il test

### Variante A — Amico legge i JSON Contabo (quella che hai chiesto)

1. Contabo condivide in sola lettura `C:\TG_TradinGo\signals`
2. gamehosting si collega in VPN e monta quella share
3. I file vengono **junction** dentro `MQL5\Files\tradingo` (MT5 legge meglio lì)
4. EA: `InpUseAbsolutePath=false`, `InpSignalsPath=tradingo\`

### Variante B — Bridge scrive diretto sulla VPS amico (spesso migliore)

1. gamehosting condivide in scrittura la sua `MQL5\Files` (o `...\Files\tradingo`)
2. Su Contabo, in `tradingo_config.json` → `mt5_instances`, aggiungi:
   `"signals_path": "\\\\10.8.0.2\\tradingo"`
3. EA amico legge locale (`InpSignalsPath=""` o `tradingo\`)

Per il **primo test di latenza** usa **A**. Se A è scomoda con sandbox MT5, passa a **B**.

---

## 1) WireGuard (Contabo = server)

Su Contabo (PowerShell admin):

1. Installa [WireGuard for Windows](https://www.wireguard.com/install/).
2. Genera chiavi (in WireGuard → Add Tunnel → Create from scratch, oppure `wg genkey`).
3. Esempio tunnel **server** `C:\Program Files\WireGuard\Data\Configurations\tg-friends.conf`:

```ini
[Interface]
PrivateKey = <PRIV_KEY_CONTABO>
Address = 10.8.0.1/24
ListenPort = 51820

[Peer]
# Amico gamehosting
PublicKey = <PUB_KEY_AMICO>
AllowedIPs = 10.8.0.2/32
```

4. Firewall Contabo — apri **UDP 51820** inbound (solo se necessario; WireGuard ascolta sul pubblico).
5. Avvia il tunnel.

IP pubblici di riferimento (aggiorna se cambiano):

| Host | Accesso tipico |
|------|----------------|
| Contabo (bridge) | `144.91.76.28` SSH/RDP come da setup |
| gamehosting amico | `185.229.236.83:27842` (RDP) |

---

## 2) WireGuard (gamehosting = client)

Su gamehosting:

```ini
[Interface]
PrivateKey = <PRIV_KEY_AMICO>
Address = 10.8.0.2/24
DNS = 1.1.1.1

[Peer]
PublicKey = <PUB_KEY_CONTABO>
Endpoint = 144.91.76.28:51820
AllowedIPs = 10.8.0.0/24
PersistentKeepalive = 25
```

Test:

```powershell
ping 10.8.0.1
```

Se ping ok, la VPN è su.

---

## 3) Share SMB dei JSON su Contabo (sola lettura)

Su Contabo:

```powershell
# Condividi la cartella signals (esempio)
$sharePath = "C:\TG_TradinGo\signals"
New-SmbShare -Name "TGSignals" -Path $sharePath -ReadAccess "Everyone" -ErrorAction SilentlyContinue
# Meglio: ReadAccess solo all'utente VPN/amico, non Everyone in produzione

# Firewall: SMB solo sulla interfaccia WireGuard (consigliato)
# Evita di aprire 445 su Internet pubblico.
```

Da gamehosting (con VPN attiva):

```powershell
dir \\10.8.0.1\TGSignals
# Devono comparire signal_ch_gold.json, ... ivan.json
```

---

## 4) Far leggere i file a MT5 sull’amico

MT5 spesso **non** apre bene UNC arbitrari. Metodo pratico:

### Opzione junction (consigliata)

Trova l’HASH del terminal amico (cartella sotto `%APPDATA%\MetaQuotes\Terminal\`).

```powershell
$files = "$env:APPDATA\MetaQuotes\Terminal\<HASH>\MQL5\Files"
New-Item -ItemType Directory -Path $files -Force | Out-Null
# Rimuovi tradingo se esiste già come cartella normale
cmd /c mklink /J "$files\tradingo" "\\10.8.0.1\TGSignals"
dir "$files\tradingo"
```

Parametri EA:

| Input | Valore |
|-------|--------|
| `InpUseAbsolutePath` | `false` |
| `InpSignalsPath` | `tradingo\` |
| `InpChannels` | `gold,forex,oro,stark,ivan` |
| `InpLotMultiplier` | basso in demo (es. `0.5` o `1.0`) |

Log atteso: `EA v2.09 started` e poi `signal_ch_*.json action=...`.

---

## 5) Misurare latenza e scostamenti

### Latenza segnale (Contabo → amico)

Sul JSON c’è `timestamp` (UTC del bridge). Sull’amico, quando l’EA logga l’azione, confronta:

```
latenza_sec ≈ ora_locale_EA - timestamp_JSON
```

Script rapido su gamehosting (poll file):

```powershell
$path = "\\10.8.0.1\TGSignals\signal_ch_oro.json"
$prev = ""
while ($true) {
  if (Test-Path $path) {
    $raw = Get-Content $path -Raw -ErrorAction SilentlyContinue
    if ($raw -and $raw -ne $prev -and $raw -match '"timestamp"\s*:\s*"([^"]+)"') {
      $ts = [datetime]::Parse($Matches[1]).ToUniversalTime()
      $now = [datetime]::UtcNow
      $ms = ($now - $ts).TotalMilliseconds
      Write-Host ("{0:u}  lag={1:n0} ms  action snippet={2}" -f $now, $ms, $raw.Substring(0, [Math]::Min(80,$raw.Length)))
      $prev = $raw
    }
  }
  Start-Sleep -Milliseconds 200
}
```

**Atteso realistico su VPN+SMB:** circa **50–300 ms** (a volte 0.5–1 s).  
Se vedi **molti secondi**, la VPN/SMB non è sana (o stai usando cloud sync per sbaglio).

### Scostamento fill (Contabo vs amico)

Su entrambi i terminali, stesso segnale:

| Campo | Dove |
|-------|------|
| `fill` nel log `[TradinGo] Opened ... fill=` | Experts |
| `slippage_points` | `tradingo_signal_stats.csv` in `MQL5\Files` |

Differenza tipica: spread + latency (amico entra qualche decina/centinaia di ms dopo).  
Se lo scostamento è grande e sistematico, valuta **variante B** (bridge scrive locale sull’amico).

---

## 6) Checklist test (1 amico gamehosting)

- [ ] WireGuard Contabo `10.8.0.1` ↔ amico `10.8.0.2`, `ping` ok
- [ ] `dir \\10.8.0.1\TGSignals` mostra i 5 JSON
- [ ] Junction `MQL5\Files\tradingo` → share Contabo
- [ ] EA v2.09 su un solo grafico, AutoTrading ON
- [ ] Segnale reale → log amico entro &lt; 1 s dal `timestamp`
- [ ] Confrontare fill Contabo vs fill amico sullo stesso `ts`

---

## 7) Sicurezza (minimo)

- Non aprire SMB (445) su Internet: solo rete WireGuard
- Share in **read-only** se usi variante A
- Utente Windows dedicato all’amico, non Administrator condiviso
- Quando il test finisce, puoi spegnere il peer WireGuard

---

## Alternativa se SMB su gamehosting è bloccato dal provider

Alcuni hosting bloccano SMB. Allora:

1. Resta WireGuard
2. Su Contabo, ogni N ms / all’evento, `robocopy` o lo stesso bridge scrive via `\\10.8.0.2\...` (variante B)
3. Oppure piccolo sync `scp`/WinSCP — di solito peggio della share diretta

Per 3 amici la soluzione “stessa VPS multi-MT5” resta più semplice in produzione; questa guida serve al **test latenza peer-to-peer**.
