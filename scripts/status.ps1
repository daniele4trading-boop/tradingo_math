param(
    [string]$SystemId = ""
)

. "$PSScriptRoot\lib_tradingo.ps1"

$systems = Get-TradinGOSystem -SystemId $SystemId
$rows = foreach ($system in @($systems)) {
    Show-TradinGOStatus -System $system
}

$rows | Format-Table -AutoSize
