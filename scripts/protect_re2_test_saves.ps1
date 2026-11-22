[CmdletBinding(DefaultParameterSetName = 'Protect')]
param(
    [Parameter(Mandatory)]
    [string]$SaveDirectory,

    [Parameter(Mandatory, ParameterSetName = 'Protect')]
    [scriptblock]$WhileProtected,

    [Parameter(Mandatory, ParameterSetName = 'Supervise')]
    [string]$GameExecutable,

    [Parameter(Mandatory, ParameterSetName = 'Supervise')]
    [string]$ReadyFile,

    [Parameter(ParameterSetName = 'Supervise')]
    [ValidateRange(1, 180)]
    [int]$LaunchTimeoutSeconds = 90,

    [Parameter(ParameterSetName = 'Supervise')]
    [switch]$PreserveOnLaunchTimeout,

    [Parameter(Mandatory, ParameterSetName = 'Restore')]
    [switch]$Restore
)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'The test save guard requires Windows.' }
$directory = Get-Item -LiteralPath $SaveDirectory -Force
$root = [IO.Path]::GetPathRoot($directory.FullName)
if ($directory -isnot [IO.DirectoryInfo] -or $directory.Name -ne 'win64_save' -or $directory.FullName -eq $root -or
    ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
    [IO.DriveInfo]::new($root).DriveFormat -ne 'NTFS') {
    throw 'Select the regular win64_save directory on a local NTFS volume.'
}
$path = $directory.FullName.TrimEnd('\')
$parent = $directory.Parent.FullName
if ($parent -eq $root -or ($directory.Parent.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'A regular non-root parent directory is required.'
}
$records = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'RE2Coop\save-guard'
$sha256 = [Security.Cryptography.SHA256]::Create()
try {
    $pathHash = [BitConverter]::ToString($sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($path.ToUpperInvariant()))).Replace('-', '')
} finally {
    $sha256.Dispose()
}
$journal = Join-Path $records "$pathHash.json"
$activePath = Join-Path $records "$pathHash.active"
$access = [Security.AccessControl.AccessControlSections]::Access

function Get-AccessSignature([string]$AccessDescriptor) {
    $descriptor = [Security.AccessControl.RawSecurityDescriptor]::new($AccessDescriptor)
    $flags = $descriptor.ControlFlags -band [Security.AccessControl.ControlFlags]'DiscretionaryAclPresent, DiscretionaryAclProtected'
    # Windows can recalculate the auto-inheritance flags when setting a DACL.
    # The protection flag and the full ordered ACEs must still match.
    $entries = foreach ($ace in $descriptor.DiscretionaryAcl) {
        $bytes = [byte[]]::new($ace.BinaryLength)
        $ace.GetBinaryForm($bytes, 0)
        [Convert]::ToBase64String($bytes)
    }
    "$flags|$($null -eq $descriptor.DiscretionaryAcl)|$($entries -join ';')"
}

function Restore-Access($Record) {
    if ($Record.schema -ne 1 -or $Record.directory -ne $path -or $Record.access -isnot [string] -or
        $Record.parent_access -isnot [string] -or
        -not $Record.files) { throw 'The recovery file does not describe the selected save directory.' }
    foreach ($file in $Record.files) {
        if ($file.name -isnot [string] -or -not $file.name -or $file.name -in '.', '..' -or
            $file.name.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0 -or $file.access -isnot [string]) {
            throw 'The recovery file contains an invalid file name or permission record.'
        }
    }
    # Windows can recompute inherited ACEs from the current parent on Set-Acl.
    # Restore ancestors first so child entries inherit from the original ACLs.
    $targets = @(@{path = $parent; access = $Record.parent_access}, @{path = $path; access = $Record.access}) +
        @($Record.files | ForEach-Object {
        @{path = Join-Path $path $_.name; access = $_.access; file = $true}
    })
    $failures = foreach ($target in $targets) {
        try {
            $destination = $target.path
            $item = Get-Item -LiteralPath $destination -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
                ($target.file -and $item -isnot [IO.FileInfo]) -or
                (-not $target.file -and $item -isnot [IO.DirectoryInfo])) { throw 'Invalid restore target.' }
            $restored = Get-Acl -LiteralPath $destination
            $restored.SetSecurityDescriptorSddlForm($target.access, $access)
            Set-Acl -LiteralPath $destination -AclObject $restored
            $actual = (Get-Acl -LiteralPath $destination).GetSecurityDescriptorSddlForm($access)
            if ((Get-AccessSignature $actual) -cne (Get-AccessSignature $target.access)) {
                throw 'The restored access rules or protection flag did not match the recorded state.'
            }
        } catch {
            "${destination}: $($_.Exception.Message)"
        }
    }
    if ($failures) {
        throw "Restore failed. Recovery file retained at $journal. $($failures -join ' ')"
    }
}

function Get-ProtectedGame([IO.FileInfo]$Executable) {
    foreach ($process in [Diagnostics.Process]::GetProcessesByName($Executable.BaseName)) {
        $matched = $false
        try {
            # Keep the handle on the Process object while checking and waiting.
            $null = $process.Handle
            if ($process.HasExited) { continue }
            if ($process.MainModule.FileName -ne $Executable.FullName) {
                throw 'Another game executable with the same process name is running.'
            }
            $matched = $true
            return $process
        } catch {
            if (-not $process.HasExited) { throw }
        } finally {
            if (-not $matched) { $process.Dispose() }
        }
    }
}

function Wait-ProtectedGame([IO.FileInfo]$Executable) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    do {
        $game = Get-ProtectedGame $Executable
        if ($game) { break }
        Start-Sleep -Milliseconds 100
    } while ($timer.Elapsed.TotalSeconds -lt $LaunchTimeoutSeconds)

    if (-not $game) { $game = Get-ProtectedGame $Executable }
    if (-not $game) { return $false }
    do {
        try {
            $game.WaitForExit()
        } finally {
            $game.Dispose()
        }
        $game = Get-ProtectedGame $Executable
    } while ($game)
    return $true
}

if ($Restore) {
    $stream = [IO.File]::Open($journal, 'Open', 'Read', 'None')
    try {
        $reader = [IO.StreamReader]::new($stream)
        $record = $reader.ReadToEnd() | ConvertFrom-Json
        Restore-Access $record
    } finally {
        if ($reader) { $reader.Dispose() }
        $stream.Dispose()
    }
    Remove-Item -LiteralPath $journal
    return
}

$supervise = $PSCmdlet.ParameterSetName -eq 'Supervise'
if ($supervise) {
    $executable = Get-Item -LiteralPath $GameExecutable -Force
    if ($executable -isnot [IO.FileInfo] -or $executable.Extension -ne '.exe' -or
        ($executable.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Expected the exact local game executable.'
    }
    $existing = Get-ProtectedGame $executable
    if ($existing) {
        $existing.Dispose()
        throw 'Close the game before preparing the protected copy.'
    }
}

$entries = @(Get-ChildItem -LiteralPath $path -Force)
if ($entries.Count -eq 0 -or ($entries | Where-Object {
    $_ -isnot [IO.FileInfo] -or ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)
})) {
    throw 'The test guard expects a flat save directory containing regular files.'
}

$handles = [Collections.Generic.List[IO.FileStream]]::new()
$record = $null
$recordStream = $null
$activeStream = $null
$restoreNeeded = $false
$restoreOnExit = $true
try {
    $null = [IO.Directory]::CreateDirectory($records)
    $recordStream = [IO.File]::Open($journal, 'CreateNew', 'Write', 'None')
    foreach ($entry in $entries) {
        $handles.Add([IO.File]::Open($entry.FullName, 'Open', 'Read', 'Read'))
    }

    $record = @{
        schema = 1
        directory = $path
        access = (Get-Acl -LiteralPath $path).GetSecurityDescriptorSddlForm($access)
        parent_access = (Get-Acl -LiteralPath $parent).GetSecurityDescriptorSddlForm($access)
        files = @(foreach ($entry in $entries) {
            @{name = $entry.Name; access = (Get-Acl -LiteralPath $entry.FullName).GetSecurityDescriptorSddlForm($access)}
        })
    }
    $content = $record | ConvertTo-Json -Compress -Depth 4
    $bytes = [Text.Encoding]::UTF8.GetBytes($content)
    $recordStream.Write($bytes, 0, $bytes.Length)
    $recordStream.Flush($true)

    $restoreNeeded = $true
    $everyone = [Security.Principal.SecurityIdentifier]::new([Security.Principal.WellKnownSidType]::WorldSid, $null)
    $rights = [Security.AccessControl.FileSystemRights]'Write, Delete'
    foreach ($targetPath in @($parent, $path) + @($entries.FullName)) {
        $targetRights = if ($targetPath -eq $parent) {
            # Windows can authorize a child deletion on the parent even when the child denies DELETE.
            [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles
        } elseif ($targetPath -eq $path) {
            $rights -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles
        } else { $rights }
        $acl = Get-Acl -LiteralPath $targetPath
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($everyone, $targetRights, 'Deny'))
        Set-Acl -LiteralPath $targetPath -AclObject $acl
        $actual = (Get-Acl -LiteralPath $targetPath).GetSecurityDescriptorSddlForm($access)
        if ((Get-AccessSignature $actual) -cne (Get-AccessSignature $acl.GetSecurityDescriptorSddlForm($access))) {
            throw 'A save ACL did not enter the guarded state.'
        }
    }
    $actual = @(Get-ChildItem -LiteralPath $path -Force | Select-Object -ExpandProperty FullName)
    if ($actual.Count -ne $entries.Count -or (Compare-Object @($entries.FullName) $actual)) {
        throw 'The directory changed while the save guard was being acquired.'
    }

    # The kernel removes this marker when the owning process exits, including a crash.
    $activeStream = [IO.FileStream]::new($activePath, [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::Read, 4096, [IO.FileOptions]::DeleteOnClose)
    $proof = @{schema = 1; directory = $path} | ConvertTo-Json -Compress
    $proofBytes = [Text.Encoding]::UTF8.GetBytes($proof)
    $activeStream.Write($proofBytes, 0, $proofBytes.Length)
    $activeStream.Flush($true)

    if ($supervise) {
        # A supervision error must leave the durable ACL recovery record.
        $restoreOnExit = $false
        [IO.File]::Open($ReadyFile, 'CreateNew', 'Write', 'None').Dispose()
        $started = Wait-ProtectedGame $executable
        # Steam can forward a launch and start the game after a timeout.
        # Keep the copy and its access restrictions when that request may still run.
        $restoreOnExit = $started -or -not $PreserveOnLaunchTimeout
        if (-not $started) { throw 'The game did not start while the protected copy was ready.' }
    } else {
        & $WhileProtected
    }
} finally {
    try {
        if ($activeStream) { $activeStream.Dispose() }
        if ($restoreNeeded -and $restoreOnExit) { Restore-Access $record }
        if ($recordStream -and $restoreOnExit) {
            $recordStream.Dispose()
            Remove-Item -LiteralPath $journal
        }
    } finally {
        if ($recordStream) { $recordStream.Dispose() }
        foreach ($handle in $handles) { $handle.Dispose() }
    }
}
