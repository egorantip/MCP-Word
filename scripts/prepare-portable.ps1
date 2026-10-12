param([switch]$AcceptDownloads)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'portable.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$runtimeDir = Join-Path $projectRoot 'runtime'
$pythonDir = Join-Path $runtimeDir 'python'
$pythonExe = Join-Path $pythonDir 'python.exe'
$packagesDir = Join-Path $runtimeDir 'site-packages'
$ollamaDir = Join-Path $runtimeDir 'ollama'
$ollamaExe = Join-Path $ollamaDir 'ollama.exe'
$logDir = Join-Path $projectRoot 'logs'
$modelsDir = Join-Path $projectRoot 'models'
foreach ($dir in @($runtimeDir, $pythonDir, $packagesDir, $ollamaDir, $logDir, $modelsDir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
$env:TEMP = Join-Path $runtimeDir 'tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $runtimeDir 'pip-cache'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null

function Write-ProgressFile([string]$Text) {
    Write-Output $Text
    [IO.File]::WriteAllText((Join-Path $logDir 'prepare-status.txt'), $Text, [Text.Encoding]::UTF8)
}
function Download([string]$Url, [string]$Destination) {
    # Windows 11 curl uses modern TLS and avoids legacy PowerShell TLS failures.
    & curl.exe --fail --location --retry 3 --connect-timeout 30 --ssl-revoke-best-effort --silent --show-error --output ($Destination + '.partial') $Url
    if ($LASTEXITCODE -ne 0) { throw ('Download failed: ' + $Url) }
    Move-Item -LiteralPath ($Destination + '.partial') -Destination $Destination -Force
}
function Wait-LocalServer([string]$Url, [int]$Seconds = 60) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    do {
        try {
            & curl.exe --fail --silent --max-time 2 --output (Join-Path $logDir 'ollama-version.json') ($Url + '/api/version')
            if ($LASTEXITCODE -eq 0) { return }
        } catch {}
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'Portable Ollama failed to start. See logs/ollama-prepare.err.log.'
}

if (-not $AcceptDownloads) {
    Add-Type -AssemblyName System.Windows.Forms
    $text = 'Download portable Python, Ollama, required libraries and Qwen 3.5 2B + 4B and Qwen3-VL 4B into this folder? Models need about 10 GB; keep at least 22 GB free for preparation. Internet is needed only for preparation. No system installation or administrator rights are required.'
    $answer = [Windows.Forms.MessageBox]::Show($text, 'Local Word - first launch', 'YesNo', 'Question')
    if ($answer -ne 'Yes') { exit 2 }
}
$ollamaProcess = $null
try {
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        Write-ProgressFile '1/4 Downloading portable Python...'
        $archive = Join-Path $runtimeDir 'python.zip'
        Download $config.python_url $archive
        if ((Get-FileHash -LiteralPath $archive -Algorithm MD5).Hash.ToLower() -ne $config.python_md5) {
            throw 'Python archive checksum does not match the pinned official release.'
        }
        Expand-Archive -LiteralPath $archive -DestinationPath $pythonDir -Force
    }
    # Paths remain relative, so moving the complete folder does not break imports.
    $pth = Join-Path $pythonDir 'python312._pth'
    [IO.File]::WriteAllText($pth, "python312.zip`r`n.`r`n..\bootstrap`r`n..\site-packages`r`n..\site-packages\win32`r`n..\site-packages\win32\lib`r`n..\site-packages\pywin32_system32`r`n..\..\`r`nimport site`r`n", [Text.Encoding]::ASCII)
    $lockHash = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'requirements.lock.txt') -Algorithm SHA256).Hash
    $marker = Join-Path $runtimeDir 'libraries.sha256'
    $needLibraries = (-not (Test-Path -LiteralPath $marker)) -or (-not (Test-Path -LiteralPath (Join-Path $runtimeDir 'prepared.json')))
    if (-not $needLibraries) { $needLibraries = ((Get-Content -LiteralPath $marker -Raw).Trim() -ne $lockHash) }
    if ($needLibraries) {
        Write-ProgressFile '2/4 Downloading and installing libraries inside the folder...'
        $bootstrapDir = Join-Path $runtimeDir 'bootstrap'
        New-Item -ItemType Directory -Path $bootstrapDir -Force | Out-Null
        if (-not (Test-Path -LiteralPath (Join-Path $bootstrapDir 'pip\__init__.py'))) {
            $getPip = Join-Path $runtimeDir 'get-pip.py'
            Download 'https://bootstrap.pypa.io/get-pip.py' $getPip
            $pipMetadata = Join-Path $runtimeDir 'pip-release.json'
            Download 'https://pypi.org/pypi/pip/26.2.1/json' $pipMetadata
            $pipRelease = Get-Content -LiteralPath $pipMetadata -Raw -Encoding UTF8 | ConvertFrom-Json
            $pipWheel = $pipRelease.urls | Where-Object { $_.filename -like 'pip-*-py3-none-any.whl' } | Select-Object -First 1
            if (-not $pipWheel) { throw 'Pinned pip wheel not found' }
            $pipWheelDir = Join-Path $runtimeDir 'bootstrap-wheels'
            New-Item -ItemType Directory -Path $pipWheelDir -Force | Out-Null
            $pipWheelPath = Join-Path $pipWheelDir $pipWheel.filename
            Download $pipWheel.url $pipWheelPath
            if ((Get-FileHash -LiteralPath $pipWheelPath -Algorithm SHA256).Hash.ToLower() -ne $pipWheel.digests.sha256) { throw 'pip checksum mismatch' }
            & $pythonExe $getPip --no-index --find-links $pipWheelDir --target $bootstrapDir --no-warn-script-location --no-cache-dir
            if ($LASTEXITCODE -ne 0) { throw 'pip bootstrap failed' }
        }
        $wheelsDir = Join-Path $runtimeDir 'wheels'
        New-Item -ItemType Directory -Path $wheelsDir -Force | Out-Null
        & $pythonExe (Join-Path $PSScriptRoot 'fetch-wheels.py')
        if ($LASTEXITCODE -ne 0) { throw 'Dependency download failed' }
        & $pythonExe -m pip install --no-cache-dir --no-index --find-links $wheelsDir --only-binary=:all: --no-compile --upgrade --target $packagesDir -r (Join-Path $projectRoot 'requirements.lock.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
        & $pythonExe -c "from word_mcp.web import create_app; from mcp import ClientSession; import docx, PIL"
        if ($LASTEXITCODE -ne 0) { throw 'Portable Python import verification failed' }
        [IO.File]::WriteAllText($marker, $lockHash, [Text.Encoding]::ASCII)
    }
    if (-not (Test-Path -LiteralPath $ollamaExe)) {
        Write-ProgressFile '3/4 Downloading standalone Ollama...'
        $releasePath = Join-Path $runtimeDir 'ollama-release-download.json'
        Download $config.ollama_release_api $releasePath
        $release = Get-Content -LiteralPath $releasePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $asset = $release.assets | Where-Object { $_.name -eq 'ollama-windows-amd64.zip' } | Select-Object -First 1
        if (-not $asset) { throw 'Official standalone Ollama archive not found for pinned version' }
        $archive = Join-Path $runtimeDir 'ollama.zip'
        Download $asset.browser_download_url $archive
        if ($asset.digest -and $asset.digest.StartsWith('sha256:')) {
            $expected = $asset.digest.Substring(7)
            if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower() -ne $expected) { throw 'Ollama checksum mismatch' }
        }
        Expand-Archive -LiteralPath $archive -DestinationPath $ollamaDir -Force
        [IO.File]::WriteAllText((Join-Path $runtimeDir 'ollama-release.json'), ($release | ConvertTo-Json -Depth 8), [Text.Encoding]::UTF8)
    }
    $env:OLLAMA_HOST = '127.0.0.1:' + $config.ollama_port
    $env:OLLAMA_MODELS = $modelsDir
    $env:OLLAMA_NO_CLOUD = '1'
    $env:OLLAMA_MAX_LOADED_MODELS = '1'
    $env:OLLAMA_NUM_PARALLEL = '1'
    $env:OLLAMA_CONTEXT_LENGTH = '4096'
    $env:OLLAMA_KEEP_ALIVE = '0'
    $env:CUDA_VISIBLE_DEVICES = '-1'
    $env:ROCR_VISIBLE_DEVICES = '-1'
    $env:GGML_VK_VISIBLE_DEVICES = '-1'
    $env:OLLAMA_VULKAN = '0'
    $env:OLLAMA_TMPDIR = $env:TEMP
    # Override only this preparation process; no user/system environment changes.
    $env:USERPROFILE = Join-Path $runtimeDir 'user'
    New-Item -ItemType Directory -Path $env:USERPROFILE -Force | Out-Null
    $ollamaUrl = 'http://' + $env:OLLAMA_HOST
    try {
        & curl.exe --fail --silent --max-time 2 --output (Join-Path $logDir 'ollama-version.json') ($ollamaUrl + '/api/version')
        if ($LASTEXITCODE -eq 0) { throw 'Ollama preparation port is already in use. Stop Local Word or change ollama_port in portable.json.' }
    } catch {
        if ($_.Exception.Message -like '*already in use*') { throw }
    }
    $ollamaProcess = Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'ollama-prepare.log') -RedirectStandardError (Join-Path $logDir 'ollama-prepare.err.log')
    Wait-LocalServer $ollamaUrl
    foreach ($model in $config.models) {
        Write-ProgressFile ('4/4 Downloading model ' + $model + '. This can take several minutes...')
        $modelLogName = $model.Replace(':', '-')
        $pullProcess = Start-Process -FilePath $ollamaExe -ArgumentList @('pull', $model) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput (Join-Path $logDir ($modelLogName + '-pull.log')) -RedirectStandardError (Join-Path $logDir ($modelLogName + '-pull.err.log'))
        if ($pullProcess.ExitCode -ne 0) { throw ('Model download failed: ' + $model + '. See logs/' + $modelLogName + '-pull.err.log') }
    }
    $inventoryPath = Join-Path $runtimeDir 'model-inventory.json'
    & curl.exe --fail --silent --max-time 15 --output $inventoryPath ($ollamaUrl + '/api/tags')
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read local model inventory' }
    $inventory = Get-Content -LiteralPath $inventoryPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifest = @{ prepared_at = [DateTime]::UtcNow.ToString('o'); python = $config.python_version; ollama = $config.ollama_version; requirements_sha256 = $lockHash; models = $inventory.models }
    [IO.File]::WriteAllText((Join-Path $runtimeDir 'prepared.json'), ($manifest | ConvertTo-Json -Depth 8), [Text.Encoding]::UTF8)
    Write-ProgressFile 'Ready. The complete folder can now be copied to another Windows x64 laptop and used offline.'
} catch {
    Write-ProgressFile ('ERROR: ' + $_.Exception.Message)
    throw
} finally {
    if ($ollamaProcess -and -not $ollamaProcess.HasExited) { Stop-Process -Id $ollamaProcess.Id -ErrorAction SilentlyContinue }
}
