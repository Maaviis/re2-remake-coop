param(
    [Parameter(Mandatory)]
    [string]$GameDirectory,
    [ValidateSet('host', 'guest')]
    [string]$Role = 'host',
    [switch]$WaitForInvite,
    [ValidateRange(1, 1800)]
    [int]$InviteWaitSeconds = 300
)

$ErrorActionPreference = 'Stop'
if ($WaitForInvite) {
    if ($PSBoundParameters.ContainsKey('Role') -and $Role -ne 'guest') {
        throw 'Auf eine Steam-Einladung kann nur die Gast-Bridge warten.'
    }
    $Role = 'guest'
}
$install = (Resolve-Path -LiteralPath $GameDirectory).Path
$expected = Join-Path $install 're2.exe'
if (-not (Test-Path -LiteralPath $expected -PathType Leaf)) {
    throw 'Der gewählte Ordner enthält keine re2.exe.'
}
$data = Join-Path $install 'reframework\data'
$bridge = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\steam_pose_bridge.py')).Path
$python = Get-Command python -CommandType Application | Select-Object -First 1 -ExpandProperty Source

function Find-Game {
    $running = @(Get-Process -Name re2 -ErrorAction SilentlyContinue)
    if ($running.Count -gt 1) {
        throw 'Die laufende RE2-Instanz gehört nicht eindeutig zu dieser Installation.'
    }
    if ($running.Count -eq 1) {
        $process = $running[0]
        $processPath = $process.Path
        if ($processPath -and $processPath -ne $expected) {
            throw 'Die laufende RE2-Instanz gehört zu einer anderen Installation.'
        }
        # The executable path can be unavailable during process startup or exit.
        $process
    }
}

$game = $null
if ($WaitForInvite) {
    $lobbyControl = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\network\steam_lobby_probe\lobby.ps1')).Path
    Write-Host 'Warte auf eine RE2-Steam-Einladung. Öffne die Einladung in Steam.'
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while ($clock.Elapsed.TotalSeconds -lt $InviteWaitSeconds) {
        $candidate = Find-Game
        if ($candidate -and $candidate.Path -eq $expected) {
            $status = $null
            try {
                $status = & $lobbyControl -Command status -GameProcessId $candidate.Id -TimeoutMilliseconds 350
            } catch [System.TimeoutException], [System.OperationCanceledException], [System.IO.IOException] {
                # The plugin pipe may not have started yet or may have closed with RE2.
            }
            if ($status -eq 'invite-pending' -and -not $candidate.HasExited) {
                $game = $candidate
                break
            }
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $game) { throw 'Zeitlimit beim Warten auf eine Steam-Einladung erreicht.' }
} else {
    $game = Find-Game
    if (-not $game) {
        $steam = Get-Process -Name steam -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Path
        if ($steam) {
            Start-Process -FilePath $steam -ArgumentList @('-applaunch', '883710') -WindowStyle Hidden
        } else {
            Start-Process -FilePath 'steam://rungameid/883710' -WindowStyle Hidden
        }
    }
    if (-not $game -or $game.Path -ne $expected) {
        $deadline = (Get-Date).AddSeconds(45)
        do {
            Start-Sleep -Milliseconds 300
            $game = Find-Game
        } until (($game -and $game.Path -eq $expected) -or (Get-Date) -ge $deadline)
    }
}
if (-not $game -or $game.Path -ne $expected) { throw 'RE2 konnte nicht gefunden werden.' }
if (-not (Test-Path -LiteralPath $data -PathType Container)) {
    $null = New-Item -ItemType Directory -Path $data
}
& $python -B $bridge --role $Role --pid $game.Id --data $data --lobby --save-catalog
exit $LASTEXITCODE
