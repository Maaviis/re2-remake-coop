# Capture only the visible foreground RE2 window without changing focus or mode.
[CmdletBinding()]
param(
    [ValidateRange(1, 2147483647)]
    [int]$GameProcessId,
    [Parameter(Mandatory)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
if (-not $GameProcessId) {
    $games = @(Get-Process -Name re2 -ErrorAction SilentlyContinue)
    if ($games.Count -ne 1) { throw 'Expected one running RE2 process; specify -GameProcessId.' }
    $GameProcessId = $games[0].Id
}
if ([IO.Path]::GetExtension($OutputPath) -ne '.png') { throw 'OutputPath must end in .png.' }
$destination = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
if (-not (Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($destination)) -PathType Container)) {
    throw 'The output directory must already exist.'
}
Add-Type -AssemblyName System.Drawing
if (-not ('Re2CoopFrameCapture' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class Re2CoopFrameCapture {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr window, out RECT rect);
    [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
}
'@
}
$previousDpi = [Re2CoopFrameCapture]::SetThreadDpiAwarenessContext([IntPtr](-4))
if ($previousDpi -eq [IntPtr]::Zero) { throw 'Could not enter per-monitor DPI mode for capture.' }
$bitmap = $null
$graphics = $null
try {
    $window = [Re2CoopFrameCapture]::GetForegroundWindow()
    $owner = [uint32]0
    [void][Re2CoopFrameCapture]::GetWindowThreadProcessId($window, [ref]$owner)
    if ($owner -ne $GameProcessId -or (Get-Process -Id $GameProcessId).ProcessName -ne 're2') {
        throw 'RE2 must already be the foreground window on the interactive desktop.'
    }
    $rect = [Re2CoopFrameCapture+RECT]::new()
    if (-not [Re2CoopFrameCapture]::GetWindowRect($window, [ref]$rect)) { throw 'Could not read RE2 window bounds.' }
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    if ($width -le 0 -or $height -le 0 -or $width -gt 16384 -or $height -gt 16384) { throw 'Invalid RE2 window bounds.' }
    $bitmap = [Drawing.Bitmap]::new($width, $height)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    if ([Re2CoopFrameCapture]::GetForegroundWindow() -ne $window) { throw 'Foreground changed before capture.' }
    $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
    if ([Re2CoopFrameCapture]::GetForegroundWindow() -ne $window) { throw 'Foreground changed during capture.' }
    $bitmap.Save($destination, [Drawing.Imaging.ImageFormat]::Png)
    [pscustomobject]@{GameProcessId = $GameProcessId; Width = $width; Height = $height; OutputPath = $destination}
} finally {
    if ($graphics) { $graphics.Dispose() }
    if ($bitmap) { $bitmap.Dispose() }
    if ($previousDpi -ne [IntPtr]::Zero) { [void][Re2CoopFrameCapture]::SetThreadDpiAwarenessContext($previousDpi) }
}
