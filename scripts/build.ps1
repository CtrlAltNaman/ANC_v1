[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

if (-not (Get-Command idf.py -ErrorAction SilentlyContinue)) {
    throw "idf.py was not found. Run the ESP-IDF export script first."
}

idf.py build
