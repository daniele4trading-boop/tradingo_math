param(
    [string]$RepoDir = "C:\TradinGO_Research",
    [string]$ApiBaseUrl = "http://127.0.0.1:8080",
    [string]$ApiKey = "dev-local-key",
    [string]$TradeSymbol = "XAUUSD",
    [int]$MaxSpreadPoints = 80,
    [double]$MaxRiskPct = 0.005
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $RepoDir)) {
    throw "RepoDir not found: $RepoDir"
}

$Source = Join-Path $RepoDir "mt5_ea\TradinGoSignalClient.mq5"
if (!(Test-Path $Source)) {
    throw "EA source not found: $Source"
}

$Targets = @(
    @{ Name="Ultima";     Origin="C:\Program Files\Ultima Markets MT5 Terminal";             Data="$env:APPDATA\MetaQuotes\Terminal\43A9BD896CCB6BF2DF5C71EA198AE39D" },
    @{ Name="STARTRADER"; Origin="C:\Program Files\STARTRADER Financial MetaTrader 5";        Data="$env:APPDATA\MetaQuotes\Terminal\5F9A67BD35361E686BC6A4D01A0B18D4" },
    @{ Name="XM";         Origin="C:\Program Files\XM MT5";                                   Data="$env:APPDATA\MetaQuotes\Terminal\656C351524AFFE300FAFE576FA4C7845" },
    @{ Name="Vantage";    Origin="C:\Program Files\Vantage International MT5";                Data="$env:APPDATA\MetaQuotes\Terminal\AE2CC2E013FDE1E3CDF010AA51C60400" }
)

$Summary = @()
foreach ($Target in $Targets) {
    $MetaEditor = Join-Path $Target.Origin "MetaEditor64.exe"
    $ExpertsDir = Join-Path $Target.Data "MQL5\Experts\TradinGo"
    $PresetsDir = Join-Path $Target.Data "MQL5\Presets"

    if (!(Test-Path $MetaEditor) -or !(Test-Path $Target.Data)) {
        $Summary += [PSCustomObject]@{
            Broker = $Target.Name
            Installed = $false
            Compiled = $false
            Result = "missing MetaEditor or data folder"
        }
        continue
    }

    New-Item -ItemType Directory -Force -Path $ExpertsDir | Out-Null
    New-Item -ItemType Directory -Force -Path $PresetsDir | Out-Null

    $Dest = Join-Path $ExpertsDir "TradinGoSignalClient.mq5"
    Copy-Item $Source $Dest -Force

    $Preset = @"
ApiBaseUrl=$ApiBaseUrl
ApiKey=$ApiKey
ClientId=$($Target.Name)-dryrun
BrokerName=$($Target.Name)
TradeSymbol=$TradeSymbol
EnableLiveTrading=false
PollSeconds=5
MagicNumber=260607
MaxSpreadPoints=$MaxSpreadPoints
MaxRiskPct=$MaxRiskPct
FixedLotFallback=0.01
RequestTimeoutMs=5000
PendingExpiryMinutes=90
"@

    $PresetPath = Join-Path $PresetsDir "TradinGoSignalClient_DRYRUN.set"
    Set-Content -Path $PresetPath -Value $Preset -Encoding ASCII

    $LogDir = Join-Path $RepoDir "runtime\logs"
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $CompileLog = Join-Path $LogDir "ea_compile_$($Target.Name).log"
    Remove-Item $CompileLog -ErrorAction SilentlyContinue

    $Process = Start-Process -FilePath $MetaEditor -ArgumentList @("/compile:$Dest", "/log:$CompileLog") -PassThru -Wait
    $LogText = Get-Content $CompileLog -ErrorAction SilentlyContinue
    $ResultLine = ($LogText | Select-String -Pattern "Result:" | Select-Object -Last 1).ToString()
    $Ex5 = Join-Path $ExpertsDir "TradinGoSignalClient.ex5"

    $Summary += [PSCustomObject]@{
        Broker = $Target.Name
        Installed = (Test-Path $Dest)
        Compiled = (Test-Path $Ex5)
        Result = $ResultLine
    }
}

$Summary | Format-Table -AutoSize
