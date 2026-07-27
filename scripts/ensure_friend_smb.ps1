#requires -Version 5.1
<#
.SYNOPSIS
  Persist Contabo -> Gamehosting SMB credentials (Tailscale UNC).

.DESCRIPTION
  Stores TradingoShare credentials with cmdkey + optional net use + logon task
  so bridge writes to \\100.x.x.x\tradingo work after reboot without retyping password.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\ensure_friend_smb.ps1 -ShareUnc "\\100.74.9.8\tradingo" -User TradingoShare
#>
[CmdletBinding()]
param(
    [string]$ShareUnc = "\\100.74.9.8\tradingo",
    [string]$User = "TradingoShare",
    [SecureString]$Password,
    [switch]$RegisterLogonTask
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info([string]$m) { Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Write-Ok([string]$m) { Write-Host "[OK]   $m" -ForegroundColor Green }

if ($ShareUnc -notmatch '^\\\\([^\\]+)\\') {
    throw "ShareUnc must look like \\HOST\share"
}
$hostName = $Matches[1]

if (-not $Password) {
    $Password = Read-Host "Password for $User on $ShareUnc" -AsSecureString
}
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

Write-Info "Storing credentials with cmdkey for target=$hostName user=$User"
cmdkey /delete:$hostName 2>$null | Out-Null
$p = Start-Process -FilePath "cmdkey.exe" -ArgumentList @("/add:$hostName", "/user:$User", "/pass:$plain") -Wait -PassThru -NoNewWindow
if ($p.ExitCode -ne 0) {
    throw "cmdkey failed exit=$($p.ExitCode)"
}
Write-Ok "cmdkey stored for $hostName"

Write-Info "Mapping share (persistent)"
net use $ShareUnc /delete /y 2>$null | Out-Null
net use $ShareUnc /user:$User $plain /persistent:yes | Out-Null
Write-Ok "net use ok: $ShareUnc"

$dir = Get-ChildItem -LiteralPath $ShareUnc -ErrorAction Stop
Write-Ok ("Share listable, files=" + @($dir).Count)

$probe = Join-Path $ShareUnc ("cred_probe_" + (Get-Date -Format "HHmmss") + ".txt")
"ok $(Get-Date -Format o)" | Set-Content -LiteralPath $probe -Encoding Ascii
Remove-Item -LiteralPath $probe -Force
Write-Ok "Write/delete probe ok"

if ($RegisterLogonTask) {
    $taskName = "TG_TradinGo_EnsureFriendSmb"
    $ps1 = Join-Path $env:ProgramData "TG_TradinGo\ensure_friend_smb_logon.ps1"
    New-Item -ItemType Directory -Path (Split-Path $ps1) -Force | Out-Null
    $logonBody = @"
`$ErrorActionPreference = 'SilentlyContinue'
net use $ShareUnc /user:$User /persistent:yes | Out-Null
if (-not (Test-Path -LiteralPath '$ShareUnc')) {
  net use $ShareUnc /user:$User /persistent:yes | Out-Null
}
"@
    Set-Content -LiteralPath $ps1 -Value $logonBody -Encoding Ascii
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ps1`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
    Write-Ok "Logon task registered: $taskName (uses cmdkey; no password in the task file)"
}

Write-Host ""
Write-Ok "Done. Bridge can write to $ShareUnc without retyping password (same Windows user)."
Write-Info "After Contabo reboot: Tailscale up + this user logon (task optional). Gamehosting: Tailscale + share + MT5/EA."
