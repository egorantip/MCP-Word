$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'portable.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$result = @{ mcpServers = @{ 'offline-word' = @{
    command = (Join-Path $projectRoot 'runtime\python\python.exe')
    args = @('-m', 'word_mcp', 'server')
    env = @{ WORD_MCP_ROOT = (Join-Path $projectRoot 'documents'); WORD_MCP_PROFILE = $config.profile; OLLAMA_HOST = ('http://127.0.0.1:' + $config.ollama_port); PYTHONUTF8 = '1' }
}}} | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText((Join-Path $projectRoot 'mcp-config.local.json'), $result, [Text.Encoding]::UTF8)
Write-Output 'Created mcp-config.local.json for this folder.'
