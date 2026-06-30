# Cursor SSH sulla VPS StatArb

VPS: `144.91.76.28` · utente: `Administrator` · porta SSH: **2222** (non 22)

## 1. Aggiungi la chiave Cursor (sulla VPS)

In **PowerShell come Amministratore**:

```powershell
C:\StatArb\scripts\add_cursor_ssh_key.bat
```

Oppure:

```powershell
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\add_cursor_ssh_key.ps1
```

Chiave pubblica Cursor:

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIINDZCEtLuu9iZwKZ37y0CbuhqzomXDq4g1M3n4UcYxN cursor-cloud-agent
```

Su Windows, per l’utente **Administrator** la chiave va in:

- `C:\ProgramData\ssh\administrators_authorized_keys` (principale)
- `C:\Users\Administrator\.ssh\authorized_keys` (backup)

## 2. Firewall

Apri la porta **2222** inbound (TCP):

```bat
netsh advfirewall firewall add rule name="OpenSSH 2222" dir=in action=allow protocol=TCP localport=2222
```

## 3. Verifica sulla VPS

```powershell
Get-Service sshd
Get-Content C:\ProgramData\ssh\administrators_authorized_keys
netstat -an | findstr ":2222"
```

Atteso: `sshd` Running, chiave `cursor-cloud-agent` presente, listener su `0.0.0.0:2222`.

## 4. Configura Cursor sul tuo PC

**Remote SSH** (Command Palette → `Remote-SSH: Open SSH Configuration File`):

```ssh-config
Host statarb-vps
    HostName 144.91.76.28
    User Administrator
    Port 2222
```

Poi: **Remote-SSH: Connect to Host** → `statarb-vps`.

Per Cloud Agents con ambiente self-hosted / pool privato, registra lo stesso host nel [dashboard Cloud Agents](https://cursor.com/dashboard?tab=cloud-agents) con IP, porta **2222**, utente `Administrator`, e la chiave che Cursor ti ha fornito (questa è la **pubblica** da installare sulla VPS — il privato resta su Cursor).

## 5. Test da un altro PC

```bash
ssh -p 2222 Administrator@144.91.76.28
```

Se chiede password invece della chiave, controlla permessi su `administrators_authorized_keys` (lo script `add_cursor_ssh_key.ps1` li imposta).
