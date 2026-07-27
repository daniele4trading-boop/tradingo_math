# Contabo + Gamehosting reboot expectations (TG TradinGo)

## Contabo — target after reboot (no manual steps)

| Component | How it starts |
|-----------|----------------|
| Tailscale | Windows **service** (Automatic) |
| SMB → Gamehosting `\\100.74.9.8\tradingo` | Task `TG_TradinGo_EnsureFriendSmb` at logon + `cmdkey` |
| Vantage MT5 + EA | Task `TG_TradinGo_VantageMT5AtLogon` (chart/EA saved in profile, AutoTrading ON) |
| Bridge `start_tradingo.bat` | Task `TG_TradinGo_BridgeAtLogon` (~45s after logon) |
| XM MT5 | Optional — keep Startup shortcut **or** disable if unused |

**Today (before setup):** bridge does **not** auto-start; reboot ≠ full TG recovery.

### Setup on Contabo (Admin PowerShell)

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$base = 'https://raw.githubusercontent.com/daniele4trading-boop/tradingo_system/cursor/journal-and-exit-hardening-8e22/scripts'
Invoke-WebRequest "$base/list_contabo_autostart.ps1" -OutFile C:\Temp\list_contabo_autostart.ps1 -UseBasicParsing
Invoke-WebRequest "$base/setup_contabo_tg_autostart.ps1" -OutFile C:\Temp\setup_contabo_tg_autostart.ps1 -UseBasicParsing

# 1) See what starts today (paste output to agent before deleting)
powershell -ExecutionPolicy Bypass -File C:\Temp\list_contabo_autostart.ps1
```

Find Vantage `terminal64.exe` (example):

```powershell
Get-ChildItem 'C:\Program Files','C:\Program Files (x86)' -Filter terminal64.exe -Recurse -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty FullName
```

Register stack (adjust exe path + disable patterns from the list):

```powershell
powershell -ExecutionPolicy Bypass -File C:\Temp\setup_contabo_tg_autostart.ps1 `
  -RegisterBridge `
  -RegisterVantage `
  -VantageTerminalExe "C:\PATH\TO\Vantage\terminal64.exe" `
  -DisableNamePatterns @('StatArb','quantlab','module','scanner') `
  -DisableXmStartupShortcuts
```

Omit `-DisableXmStartupShortcuts` if you still want XM to open.

Confirm SMB task exists:

```powershell
Get-ScheduledTask | Where-Object { $_.TaskName -like 'TG_TradinGo_*' } | Format-Table TaskName, State
```

Must include: `EnsureFriendSmb`, `BridgeAtLogon`, `VantageMT5AtLogon`.

---

## Gamehosting — target after reboot

| Component | How it starts |
|-----------|----------------|
| Tailscale | Service Automatic |
| SMB share `tradingo` | System share (always) |
| Ultima MT5 + EA | Startup shortcut or scheduled task; chart+EA in profile; AutoTrading ON |
| Junction `MQL5\Files\tradingo` | Persists on disk |
| Moneta (later) | Same pattern on its terminal hash |

Gamehosting does **not** run the bridge. It only needs MT5+EA reading `tradingo\`.

---

## Quick validation after a Contabo reboot

1. Tailscale connected  
2. `dir \\100.74.9.8\tradingo` works without password prompt  
3. Bridge window open, log `v2.08` + `In ascolto`  
4. Vantage Experts: EA running  
5. `powershell -File C:\Temp\monitor_friend_link.ps1` → all OK  
