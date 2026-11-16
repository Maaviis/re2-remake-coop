param(
    [Parameter(Mandatory)]
    [string]$GameDirectory,
    [ValidateSet('host', 'guest')]
    [string]$Role = 'host'
)

$ErrorActionPreference = 'Stop'
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
    if ($running.Count -gt 1 -or ($running.Count -eq 1 -and $running[0].Path -ne $expected)) {
        throw 'Die laufende RE2-Instanz gehört nicht eindeutig zu dieser Installation.'
    }
    $running | Select-Object -First 1
}

$game = Find-Game
if (-not $game) {
    $steam = Get-Process -Name steam -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Path
    if ($steam) {
        Start-Process -FilePath $steam -ArgumentList @('-applaunch', '883710') -WindowStyle Hidden
    } else {
        Start-Process -FilePath 'steam://rungameid/883710' -WindowStyle Hidden
    }
    $deadline = (Get-Date).AddSeconds(45)
    do {
        Start-Sleep -Milliseconds 300
        $game = Find-Game
    } until ($game -or (Get-Date) -ge $deadline)
}
if (-not $game) { throw 'RE2 konnte nicht gefunden werden.' }
if (-not (Test-Path -LiteralPath $data -PathType Container)) {
    $null = New-Item -ItemType Directory -Path $data
}
& $python -B $bridge --role $Role --pid $game.Id --data $data --lobby --save-catalog
exit $LASTEXITCODE
