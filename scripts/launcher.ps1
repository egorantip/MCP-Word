$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'portable.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$hash = [Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLower()))
$mutexName = 'Local\OfflineWord-' + [BitConverter]::ToString($hash).Replace('-', '')
$created = $false
$mutex = New-Object Threading.Mutex($true, $mutexName, [ref]$created)
$appUrl = 'http://127.0.0.1:' + $config.app_port
if (-not $created) { Start-Process $appUrl; $mutex.Dispose(); exit }
$logDir = Join-Path $projectRoot 'logs'
try { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
catch {
    [Windows.Forms.MessageBox]::Show('This folder must be writable. Move MCP Word outside Program Files, for example to your Desktop or C:\MCP Word.', 'Local Word', 'OK', 'Error') | Out-Null
    $mutex.ReleaseMutex()
    $mutex.Dispose()
    exit 1
}
$pythonExe = Join-Path $projectRoot 'runtime\python\python.exe'
$ollamaExe = Join-Path $projectRoot 'runtime\ollama\ollama.exe'
$ollamaProcess = $null
$webProcess = $null
$form = New-Object Windows.Forms.Form
$form.Text = 'Local Word'
$form.ClientSize = New-Object Drawing.Size(570, 235)
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object Drawing.Font('Segoe UI', 10)
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$label = New-Object Windows.Forms.Label
$label.Location = New-Object Drawing.Point(22, 22)
$label.Size = New-Object Drawing.Size(525, 130)
$label.Text = 'Preparing Local Word...'
$form.Controls.Add($label)
$openButton = New-Object Windows.Forms.Button
$openButton.Text = 'Open editor'
$openButton.Location = New-Object Drawing.Point(22, 172)
$openButton.Size = New-Object Drawing.Size(190, 38)
$openButton.Enabled = $false
$openButton.Add_Click({ Start-Process $appUrl })
$form.Controls.Add($openButton)
$stopButton = New-Object Windows.Forms.Button
$stopButton.Text = 'Stop and close'
$stopButton.Location = New-Object Drawing.Point(232, 172)
$stopButton.Size = New-Object Drawing.Size(190, 38)
$stopButton.Add_Click({ $form.Close() })
$form.Controls.Add($stopButton)
$form.Show()
function Set-Status([string]$Text) { $label.Text = $Text; [Windows.Forms.Application]::DoEvents() }
function Wait-Ready([string]$Url, [string]$Path, $Process) {
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    do {
        if ($Process.HasExited) { throw 'Service stopped unexpectedly. Check the logs folder.' }
        try {
            & curl.exe --fail --silent --max-time 2 --output (Join-Path $logDir 'health.json') ($Url + $Path)
            if ($LASTEXITCODE -eq 0) { return }
        } catch {}
        [Windows.Forms.Application]::DoEvents()
        if ($form.IsDisposed) { throw 'Launch cancelled' }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'Service startup timed out. Check the logs folder.'
}
try {
    $needsPreparation = -not ((Test-Path -LiteralPath $pythonExe) -and (Test-Path -LiteralPath $ollamaExe) -and (Test-Path -LiteralPath (Join-Path $projectRoot 'runtime\prepared.json')))
    if (-not $needsPreparation) {
        $manifest = Get-Content -LiteralPath (Join-Path $projectRoot 'runtime\prepared.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $lockHash = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'requirements.lock.txt') -Algorithm SHA256).Hash
        $needsPreparation = $manifest.requirements_sha256 -ne $lockHash
        foreach ($model in $config.models) {
            $parts = $model.Split(':')
            $modelManifest = Join-Path $projectRoot ('models\manifests\registry.ollama.ai\library\' + $parts[0] + '\' + $parts[1])
            if (-not (Test-Path -LiteralPath $modelManifest)) { $needsPreparation = $true }
        }
    }
    if ($needsPreparation) {
        Set-Status 'Some portable components are missing. Download permission is required.'
        $answer = [Windows.Forms.MessageBox]::Show($form, 'Download Python, Ollama, required libraries and Qwen 3.5 2B + 4B and Qwen3-VL 4B into this folder? Models need about 10 GB. Keep at least 22 GB free. After preparation the complete folder works offline. Nothing is installed system-wide.', 'Local Word - download components', 'YesNo', 'Question')
        if ($answer -ne 'Yes') { $form.Close(); exit }
        $script = Join-Path $PSScriptRoot 'prepare-portable.ps1'
        $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $script + '" -AcceptDownloads'
        $preparation = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'prepare.log') -RedirectStandardError (Join-Path $logDir 'prepare.err.log')
        while (-not $preparation.HasExited) {
            $statusFile = Join-Path $logDir 'prepare-status.txt'
            if (Test-Path -LiteralPath $statusFile) { Set-Status (Get-Content -LiteralPath $statusFile -Raw -Encoding UTF8) }
            [Windows.Forms.Application]::DoEvents()
            if ($form.IsDisposed) { $preparation.WaitForExit(); throw 'Preparation completed; launch was cancelled' }
            Start-Sleep -Milliseconds 250
        }
        if ($preparation.ExitCode -ne 0) { throw 'Preparation failed. Open logs/prepare.err.log for details.' }
    }
    $env:WORD_MCP_ROOT = Join-Path $projectRoot 'documents'
    $env:WORD_MCP_PROFILE = $config.profile
    $env:OLLAMA_HOST = '127.0.0.1:' + $config.ollama_port
    $env:OLLAMA_MODELS = Join-Path $projectRoot 'models'
    $env:OLLAMA_NO_CLOUD = '1'
    $env:OLLAMA_MAX_LOADED_MODELS = '1'
    $env:OLLAMA_NUM_PARALLEL = '1'
    $env:OLLAMA_CONTEXT_LENGTH = '4096'
    $env:OLLAMA_KEEP_ALIVE = '0'
    $env:CUDA_VISIBLE_DEVICES = '-1'
    $env:ROCR_VISIBLE_DEVICES = '-1'
    $env:GGML_VK_VISIBLE_DEVICES = '-1'
    $env:OLLAMA_VULKAN = '0'
    $env:PYTHONUTF8 = '1'
    $env:TEMP = Join-Path $projectRoot 'runtime\tmp'
    $env:TMP = $env:TEMP
    $env:OLLAMA_TMPDIR = $env:TEMP
    New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
    foreach ($port in @($config.app_port, $config.ollama_port)) {
        $probe = New-Object Net.Sockets.TcpClient
        try { $probe.Connect('127.0.0.1', $port); throw ('Port ' + $port + ' is occupied. Change ports in portable.json.') }
        catch [Net.Sockets.SocketException] {} finally { $probe.Dispose() }
    }
    Set-Status 'Starting local Ollama...'
    # Give the Ollama child its own profile for keys/config; restore the parent
    # before opening the user's browser. This never changes Windows settings.
    $originalProfile = $env:USERPROFILE
    try {
        $env:USERPROFILE = Join-Path $projectRoot 'runtime\user'
        New-Item -ItemType Directory -Path $env:USERPROFILE -Force | Out-Null
        $ollamaProcess = Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'ollama.log') -RedirectStandardError (Join-Path $logDir 'ollama.err.log')
    } finally { $env:USERPROFILE = $originalProfile }
    Wait-Ready ('http://' + $env:OLLAMA_HOST) '/api/version' $ollamaProcess
    Set-Status 'Starting document editor...'
    $webProcess = Start-Process -FilePath $pythonExe -ArgumentList @('-m', 'word_mcp', 'web', '--port', $config.app_port) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'web.log') -RedirectStandardError (Join-Path $logDir 'web.err.log')
    Wait-Ready $appUrl '/health' $webProcess
    Set-Status ('Local Word is running offline.' + "`r`n`r`n" + 'Qwen 3.5 2B/4B for text. Qwen3-VL 4B for images.' + "`r`n`r`n" + 'Keep this window open. Close it to stop both services.')
    $openButton.Enabled = $true
    Start-Process $appUrl
    while (-not $form.IsDisposed) {
        [Windows.Forms.Application]::DoEvents()
        if ($webProcess.HasExited -or $ollamaProcess.HasExited) { throw 'A local service stopped. Check the logs folder.' }
        Start-Sleep -Milliseconds 200
    }
} catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $logDir 'launcher.err.log') -Encoding UTF8
    if (-not $form.IsDisposed) { [Windows.Forms.MessageBox]::Show($form, $_.Exception.Message, 'Local Word', 'OK', 'Error') | Out-Null }
} finally {
    foreach ($process in @($webProcess, $ollamaProcess)) {
        if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -ErrorAction SilentlyContinue }
    }
    if (-not $form.IsDisposed) { $form.Close() }
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
