# Canale stabile VPS: SSH o WinRM

RDP headless funziona per emergenza, ma e' fragile: dipende da sessione grafica, clipboard, layout tastiera e finestre aperte. Per gestione professionale serve un canale testuale stabile.

## Opzione consigliata: OpenSSH Server su Windows

Da una sessione RDP come Administrator, aprire PowerShell come amministratore.

### 1. Installare OpenSSH Server

```powershell
Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
```

### 2. Avviare e rendere automatico il servizio

```powershell
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
Get-Service sshd
```

### 3. Firewall

```powershell
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```

### 4. Verificare file configurazione

```powershell
notepad C:\ProgramData\ssh\sshd_config
```

Per partire in modo semplice, verificare che non siano bloccati:

```text
PasswordAuthentication yes
PubkeyAuthentication yes
```

Poi:

```powershell
Restart-Service sshd
```

### 5. Test da Cloud Agent

```bash
ssh Administrator@144.91.76.28 "hostname && whoami"
```

Se continua a fare reset prima del login, controllare:

```powershell
Get-Content C:\ProgramData\ssh\logs\sshd.log -Tail 100
Get-EventLog -LogName Application -Source sshd -Newest 50
```

## Opzione alternativa: WinRM

WinRM e' comodo per PowerShell remoto, ma va configurato con attenzione.

### 1. Abilitare PowerShell Remoting

```powershell
Enable-PSRemoting -Force
winrm quickconfig -force
```

### 2. Consentire Basic/NTLM se necessario

```powershell
winrm set winrm/config/service/auth '@{Basic="true"}'
winrm set winrm/config/service '@{AllowUnencrypted="true"}'
```

Nota: `AllowUnencrypted=true` e' accettabile solo temporaneamente o dietro firewall ristretto. In produzione meglio HTTPS 5986.

### 3. Firewall

```powershell
Enable-NetFirewallRule -DisplayGroup "Windows Remote Management"
```

### 4. Test locale sulla VPS

```powershell
winrm enumerate winrm/config/listener
Test-WSMan localhost
```

### 5. Test da Cloud Agent

```python
import winrm
s = winrm.Session(
    "http://144.91.76.28:5985/wsman",
    auth=("Administrator", "PASSWORD"),
    transport="ntlm",
)
r = s.run_cmd("hostname")
print(r.status_code, r.std_out.decode())
```

## Cosa deve fare Daniele

Serve accesso RDP manuale solo per:

1. aprire PowerShell come Administrator;
2. eseguire i comandi sopra;
3. verificare che firewall/Contabo non blocchino 22 o 5985/5986;
4. comunicarmi quando SSH o WinRM risponde.

Il resto posso farlo io via repo/script.
