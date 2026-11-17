param([string]$ProbeDirectory, [string]$HoldDirectory, [string]$ReadyPath)

$ErrorActionPreference = 'Stop'
$guard = Join-Path $PSScriptRoot '..\scripts\protect_re2_test_saves.ps1'

if ($HoldDirectory) {
    & $guard -SaveDirectory $HoldDirectory -WhileProtected {
        [IO.File]::WriteAllText($ReadyPath, 'ready')
        Start-Sleep -Seconds 18
    }
    return
}

function Assert-Blocked([string]$Operation, [scriptblock]$Attempt) {
    try {
        & $Attempt
    } catch {
        $failure = $_.Exception.GetBaseException()
        if ($failure -is [UnauthorizedAccessException] -or $failure -is [IO.IOException]) { return }
        throw
    }
    throw "Windows permitted $Operation while the directory was guarded."
}

if ($ProbeDirectory) {
    $first = Join-Path $ProbeDirectory 'data000.bin'
    $spare = Join-Path $ProbeDirectory 'data023.bin'
    $folder = Join-Path $ProbeDirectory 'new-directory'
    $source = Join-Path (Split-Path -Parent $ProbeDirectory) 'replacement.bin'
    $movedDirectory = "$ProbeDirectory-renamed"
    if ([IO.File]::ReadAllText($first) -cne 'baseline-000') { throw 'The guarded file became unreadable.' }

    Assert-Blocked 'write access' { [IO.File]::Open($first, 'Open', 'Write', 'ReadWrite').Dispose() }
    Assert-Blocked 'truncation' { [IO.File]::Open($first, 'Create', 'Write', 'ReadWrite').Dispose() }
    Assert-Blocked 'deletion' { [IO.File]::Delete($first) }
    Assert-Blocked 'replacement' { [IO.File]::Move($source, $first, $true) }
    Assert-Blocked 'file creation' { [IO.File]::WriteAllText($spare, 'unexpected') }
    Assert-Blocked 'directory creation' { $null = [IO.Directory]::CreateDirectory($folder) }
    Assert-Blocked 'directory rename' {
        [IO.Directory]::Move($ProbeDirectory, $movedDirectory)
        [IO.Directory]::Move($movedDirectory, $ProbeDirectory)
    }
    'Verified reading and blocked writes, truncation, deletion, replacement, new files and directories, and a directory rename.'
    return
}

$entryPoint = $PSCommandPath
$work = [IO.Directory]::CreateTempSubdirectory('re2-save-storage-Straße-')
$saveDirectory = [IO.Directory]::CreateDirectory((Join-Path $work.FullName 'win64_save')).FullName
$first = Join-Path $saveDirectory 'data000.bin'
$second = Join-Path $saveDirectory 'data001.bin'
$source = Join-Path $work.FullName 'replacement.bin'
$directoryHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($saveDirectory.ToUpperInvariant())))
$recovery = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) "RE2Coop\save-guard\$directoryHash.json"
$activeMarker = [IO.Path]::ChangeExtension($recovery, '.active')

function Assert-StorageGuardState([bool]$Expected) {
    $check = @'
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from readonly_save_control import _storage_guard_active
actual = _storage_guard_active(Path(sys.argv[2]).resolve())
if actual != (sys.argv[3] == "True"):
    raise RuntimeError("Unexpected active Windows save guard state")
'@
    python -B -c $check (Join-Path $PSScriptRoot '..') $saveDirectory ([string]$Expected)
    if ($LASTEXITCODE -ne 0) { throw 'The Python storage guard check failed.' }
}

function Get-TestAccess([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path
    # Windows may recalculate the automatic inheritance flags without changing effective rules.
    "$($acl.AreAccessRulesProtected)|$($acl.AccessToString)"
}
try {
    [IO.File]::WriteAllText($first, 'baseline-000')
    [IO.File]::WriteAllText($second, 'baseline-001')
    [IO.File]::WriteAllText($source, 'replacement')
    $hashes = Get-FileHash -LiteralPath $first,$second
    $original = @{}
    foreach ($path in @($work.FullName, $saveDirectory, $first, $second)) {
        $original[$path] = Get-TestAccess $path
    }
    function Assert-OriginalAccess {
        foreach ($path in $original.Keys) {
            if ((Get-TestAccess $path) -cne $original[$path]) {
                throw 'An original ACL was not restored.'
            }
        }
        if (Test-Path -LiteralPath $recovery) { throw 'A stale recovery record was left.' }
        if (Test-Path -LiteralPath $activeMarker) { throw 'A stale active marker was left.' }
        Assert-StorageGuardState $false
    }

    $writer = [IO.File]::Open($first, 'Open', 'Write', 'ReadWrite')
    try {
        Assert-Blocked 'a guard with a writer already open' {
            & $guard -SaveDirectory $saveDirectory -WhileProtected { throw 'Started with a writable file handle.' }
        }
    } finally { $writer.Dispose() }
    Assert-OriginalAccess

    & $guard -SaveDirectory $saveDirectory -WhileProtected {
        Assert-StorageGuardState $true
        pwsh -NoProfile -File $entryPoint -ProbeDirectory $saveDirectory
        if ($LASTEXITCODE -ne 0) { throw 'The second-process save probe failed.' }
    }
    Assert-OriginalAccess
    foreach ($record in $hashes) {
        if ((Get-FileHash -LiteralPath $record.Path).Hash -ne $record.Hash) { throw 'A fixture file changed.' }
    }

    try {
        & $guard -SaveDirectory $saveDirectory -WhileProtected { throw 'test child failure' }
        throw 'The protected block did not report its failure.'
    } catch {
        if ($_.Exception.Message -ne 'test child failure') { throw }
    }
    Assert-OriginalAccess

    $ready = Join-Path $work.FullName 'ready.txt'
    $worker = Start-Process -FilePath (Get-Command pwsh -CommandType Application | Select-Object -First 1).Source `
        -ArgumentList @('-NoProfile', '-File', ('"' + $entryPoint + '"'), '-HoldDirectory',
            ('"' + $saveDirectory + '"'), '-ReadyPath', ('"' + $ready + '"')) `
        -PassThru -WindowStyle Hidden
    try {
        $until = [DateTimeOffset]::UtcNow.AddSeconds(7)
        while (-not (Test-Path -LiteralPath $ready) -and -not $worker.HasExited -and [DateTimeOffset]::UtcNow -lt $until) {
            Start-Sleep -Milliseconds 50
        }
        if (-not (Test-Path -LiteralPath $ready) -or $worker.HasExited) { throw 'Guard process did not become ready.' }
        Assert-StorageGuardState $true
        Assert-Blocked 'active recovery file access' { [IO.File]::ReadAllText($recovery) | Out-Null }
        Assert-Blocked 'a second guard on the same directory' {
            & $guard -SaveDirectory $saveDirectory -WhileProtected { throw 'Should not reach a second protected block.' }
        }
    } finally {
        if (-not $worker.HasExited) { $worker.Kill(); $worker.WaitForExit() }
    }
    Assert-StorageGuardState $false
    if (Test-Path -LiteralPath $activeMarker) { throw 'The kernel left an active marker after process termination.' }
    try {
        @{schema = 1; directory = $saveDirectory} | ConvertTo-Json -Compress | Set-Content -LiteralPath $activeMarker
        Assert-StorageGuardState $false
    } finally { Remove-Item -LiteralPath $activeMarker -ErrorAction SilentlyContinue }
    pwsh -NoProfile -File $entryPoint -ProbeDirectory $saveDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Save protection did not persist after the owner process exited.' }
    & $guard -SaveDirectory $saveDirectory -Restore
    Assert-OriginalAccess
    foreach ($record in $hashes) {
        if ((Get-FileHash -LiteralPath $record.Path).Hash -ne $record.Hash) { throw 'A recovered fixture file changed.' }
    }
    [IO.File]::WriteAllText($first, 'writable again')
    [IO.File]::WriteAllText((Join-Path $saveDirectory 'restored.bin'), 'new file permitted again')
    'Verified the original ACL and write access after success, an exception, and abrupt process termination.'
    'Verified Python detects the active guard, rejects an unlocked marker and sees termination cleanup.'
} finally {
    if (Test-Path -LiteralPath $recovery) {
        & $guard -SaveDirectory $saveDirectory -Restore
    }
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if ($work.FullName.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -and
        $work.Name.StartsWith('re2-save-storage-')) {
        [IO.Directory]::Delete($work.FullName, $true)
    }
}
