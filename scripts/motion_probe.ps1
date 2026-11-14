param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Start', 'Stop')]
    [string] $Action,

    [Parameter(Mandatory = $true)]
    [string] $DataDirectory
)

$directory = (Resolve-Path -LiteralPath $DataDirectory -ErrorAction Stop).Path
$destination = Join-Path $directory 're2_coop_motion_command.json'
$temporary = Join-Path $directory ('.re2_coop_motion_command_' + [guid]::NewGuid().ToString('N') + '.tmp')
$command = @{
    schema = 1
    action = $Action.ToLowerInvariant()
    nonce = [guid]::NewGuid().ToString('D')
    issued_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
} | ConvertTo-Json -Compress

try {
    [System.IO.File]::WriteAllText($temporary, $command, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::Move($temporary, $destination, $true)
} finally {
    if ([System.IO.File]::Exists($temporary)) {
        [System.IO.File]::Delete($temporary)
    }
}

Write-Output "Motion probe $($Action.ToLowerInvariant()) requested."
