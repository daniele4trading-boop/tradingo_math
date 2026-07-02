param(
    [string]$SystemId = ""
)

. "$PSScriptRoot\lib_tradingo.ps1"

$systems = Get-TradinGOSystem -SystemId $SystemId
foreach ($system in @($systems)) {
    Start-TradinGOSystem -System $system
}
