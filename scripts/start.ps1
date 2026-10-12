$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$errorLog = Join-Path $projectRoot 'logs\launcher.err.log'
try {
    New-Item -ItemType Directory -Path (Split-Path $errorLog) -Force | Out-Null
    & (Join-Path $PSScriptRoot 'launcher.ps1')
} catch {
    $details = $_ | Out-String
    try { $details | Set-Content -LiteralPath $errorLog -Encoding UTF8 } catch {}
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show(($details + "`r`nDetails: " + $errorLog), 'Local Word - startup error', 'OK', 'Error') | Out-Null
    exit 1
}
