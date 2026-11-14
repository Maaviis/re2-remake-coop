# Send an allowlisted command to the locally running RE2 plugin.
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('create', 'invite-dialog', 'leave', 'status')]
    [string]$Command,

    [ValidateRange(1, 2147483647)]
    [int]$GameProcessId
)

$ErrorActionPreference = 'Stop'
if (-not $GameProcessId) {
    $games = @(Get-Process -Name re2 -ErrorAction SilentlyContinue)
    if ($games.Count -ne 1) {
        throw 'Expected one running RE2 process. Use -GameProcessId to select an instance.'
    }
    $GameProcessId = $games[0].Id
}

$pipeName = "re2-coop-steam-lobby-$GameProcessId"
$client = [IO.Pipes.NamedPipeClientStream]::new('.', $pipeName, [IO.Pipes.PipeDirection]::InOut, [IO.Pipes.PipeOptions]::Asynchronous)
$timeout = [Threading.CancellationTokenSource]::new()
try {
    $client.Connect(3000)
    $timeout.CancelAfter(3000)
    $bytes = [Text.Encoding]::ASCII.GetBytes($Command.ToLowerInvariant())
    $client.Write($bytes, 0, $bytes.Length)
    $buffer = [byte[]]::new(128)
    $count = $client.ReadAsync($buffer, 0, $buffer.Length, $timeout.Token).GetAwaiter().GetResult()
    if (-not $count) { throw 'The RE2 plugin closed the connection without a reply.' }
    $reply = [Text.Encoding]::ASCII.GetString($buffer, 0, $count)
    if ($reply.StartsWith('error ')) { throw $reply }
    $reply
} finally {
    $client.Dispose()
    $timeout.Dispose()
}
