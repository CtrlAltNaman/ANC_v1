[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

if (-not (Get-Command idf.py -ErrorAction SilentlyContinue)) {
    throw "idf.py was not found. Run the ESP-IDF export script first."
}

$firmwareRoot = Join-Path $PSScriptRoot "..\firmware\esp32"
Push-Location $firmwareRoot
try {
    idf.py build
} finally {
    Pop-Location
}
