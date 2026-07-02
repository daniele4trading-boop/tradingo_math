param(
    [Parameter(Mandatory = $true)]
    [string]$SystemId
)

. "$PSScriptRoot\lib_tradingo.ps1"

$system = Get-TradinGOSystem -SystemId $SystemId
Stop-TradinGOSystem -System $system
Start-Sleep -Seconds 2
Start-TradinGOSystem -System $system
