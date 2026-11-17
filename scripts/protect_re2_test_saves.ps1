[CmdletBinding(DefaultParameterSetName = 'Protect')]
param(
    [Parameter(Mandatory)]
    [string]$SaveDirectory,

    [Parameter(Mandatory, ParameterSetName = 'Protect')]
    [scriptblock]$WhileProtected,

    [Parameter(Mandatory, ParameterSetName = 'Restore')]
    [switch]$Restore
)

$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'The test save guard requires Windows.' }
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
$pathHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($path.ToUpperInvariant())))
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
    $targets = @($Record.files | ForEach-Object {
        @{path = Join-Path $path $_.name; access = $_.access; file = $true}
    }) + @(@{path = $path; access = $Record.access}, @{path = $parent; access = $Record.parent_access})
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

    & $WhileProtected
} finally {
    try {
        if ($activeStream) { $activeStream.Dispose() }
        if ($restoreNeeded) { Restore-Access $record }
        if ($recordStream) {
            $recordStream.Dispose()
            Remove-Item -LiteralPath $journal
        }
    } finally {
        if ($recordStream) { $recordStream.Dispose() }
        foreach ($handle in $handles) { $handle.Dispose() }
    }
}
