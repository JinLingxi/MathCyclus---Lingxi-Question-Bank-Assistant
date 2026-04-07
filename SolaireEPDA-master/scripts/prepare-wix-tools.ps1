# Pre-download WiX 3.14 binaries into Tauri bundler cache (same path as tauri-bundler msi/mod.rs).
# Fixes "timeout: global" when cargo/npm tauri cannot finish downloading from GitHub.
# Run: .\scripts\prepare-wix-tools.ps1   [-Force]

param([switch]$Force)

$ErrorActionPreference = "Stop"

$WixUrl = "https://github.com/wixtoolset/wix3/releases/download/wix3141rtm/wix314-binaries.zip"
$ExpectedSha256 = "6ac824e1642d6f7277d0ed7ea09411a508f6116ba6fae0aa5f2c7daa2ff43d31"
$Dest = Join-Path $env:LOCALAPPDATA "cache\tauri\WixTools314"
$Required = @(
  "candle.exe",
  "candle.exe.config",
  "darice.cub",
  "light.exe",
  "light.exe.config",
  "wconsole.dll",
  "winterop.dll",
  "wix.dll",
  "WixUIExtension.dll",
  "WixUtilExtension.dll"
)

function Test-WixComplete {
  foreach ($name in $Required) {
    if (-not (Test-Path (Join-Path $Dest $name))) {
      return $false
    }
  }
  return $true
}

if (-not $Force -and (Test-WixComplete)) {
  Write-Host "WiX tools already present: $Dest" -ForegroundColor Green
  exit 0
}

Write-Host "Downloading WiX 3.14 to $Dest (long timeout)..." -ForegroundColor Cyan
if (Test-Path $Dest) {
  Remove-Item -Recurse -Force $Dest
}
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

$zip = Join-Path $env:TEMP ("wix314-binaries-" + [guid]::NewGuid().ToString("n") + ".zip")
try {
  Invoke-WebRequest -Uri $WixUrl -OutFile $zip -TimeoutSec 1800 -UseBasicParsing
  $hash = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($hash -ne $ExpectedSha256) {
    throw "SHA256 mismatch. Expected $ExpectedSha256 got $hash"
  }
  Expand-Archive -LiteralPath $zip -DestinationPath $Dest -Force
} finally {
  Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
}

if (-not (Test-WixComplete)) {
  Write-Error "WiX extract incomplete under $Dest"
  exit 1
}

Write-Host "WiX ready. Retry: npm run tauri:build (or .\scripts\build.ps1)" -ForegroundColor Green
