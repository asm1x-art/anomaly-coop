# Fetches NVIDIA's DLSS SDK (the parts the engine needs) into src\3rd party\nvngx_dlss. It is not in the repository:
# NVIDIA's licence lets it go out only inside an application. Without it the engine builds with DLSS off.
#   include\*.h            headers (compiled in)
#   lib\nvsdk_ngx_d.lib    NGX, linked into the exe (dynamic CRT)
#   bin\nvngx_dlss.dll     DLSS itself: goes next to AnomalyDX11.exe in the game's bin
#   LICENSE.txt            NVIDIA RTX SDKs licence: goes with the dll (as DLSS-LICENSE.txt)
# Usage: powershell -ExecutionPolicy Bypass -File tools\dlss\get_dlss_sdk.ps1
param(
    [string]$Version = "310.9.16",
    [string]$Sha256 = "418d6c685b062855f970d55d1e172eff834658a17b3483aaffddf44d5b0cb026"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$dest = Join-Path $root "src\3rd party\nvngx_dlss"
$zip = Join-Path ([IO.Path]::GetTempPath()) "DLSS-$Version.zip"

if (-not (Test-Path $zip) -or (Get-FileHash $zip -Algorithm SHA256).Hash -ne $Sha256.ToUpper()) {
    Write-Host "Downloading DLSS SDK $Version (about 700 MB)..."
    Invoke-WebRequest "https://github.com/NVIDIA/DLSS/archive/refs/tags/v$Version.zip" -OutFile $zip -UseBasicParsing
}
if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne $Sha256.ToUpper()) { throw "SHA-256 mismatch for $zip" }

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($zip)
try {
    $prefix = "DLSS-$Version/"
    $want = @{
        "include/" = "include";
        "lib/Windows_x86_64/x64/nvsdk_ngx_d.lib" = "lib";
        "lib/Windows_x86_64/rel/nvngx_dlss.dll" = "bin";
        "LICENSE.txt" = "."
    }
    foreach ($e in $archive.Entries) {
        if (-not $e.FullName.StartsWith($prefix) -or $e.Name -eq "") { continue }
        $rel = $e.FullName.Substring($prefix.Length)
        foreach ($k in $want.Keys) {
            $match = if ($k.EndsWith("/")) { $rel.StartsWith($k) -and $rel.EndsWith(".h") } else { $rel -eq $k }
            if ($match) {
                $dir = Join-Path $dest $want[$k]
                New-Item -ItemType Directory -Force $dir | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($e, (Join-Path $dir $e.Name), $true)
            }
        }
    }
} finally { $archive.Dispose() }
Write-Host "DLSS SDK $Version in $dest"
