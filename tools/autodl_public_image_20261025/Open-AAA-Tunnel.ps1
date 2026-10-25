[CmdletBinding()]
param(
    [string]$AaaSshHost = '',
    [int]$AaaSshPort = 0,
    [ValidateRange(1,65535)][int]$AstrBotLocalPort = 6185,
    [ValidateRange(1,65535)][int]$ComfyLocalPort = 8188,
    [ValidateRange(1,65535)][int]$HubLocalPort = 6278,
    [ValidateRange(1,65535)][int]$NapCatLocalPort = 6099,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'

function Test-AaaHost([string]$Value) {
    return ($Value.Length -le 253 -and $Value -match '^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$' -and $Value -notmatch '\.\.')
}

$AaaSshCommand = Get-Command ssh.exe -ErrorAction SilentlyContinue
$AaaSshExe = if ($AaaSshCommand) { $AaaSshCommand.Source } else { '' }
if (-not $AaaSshExe) {
    foreach ($AaaCandidate in @("$env:WINDIR\System32\OpenSSH\ssh.exe", "$env:WINDIR\Sysnative\OpenSSH\ssh.exe")) {
        if (Test-Path -LiteralPath $AaaCandidate -PathType Leaf) { $AaaSshExe=$AaaCandidate; break }
    }
}
if (-not $AaaSshExe) {
    Write-Host 'OpenSSH CLIENT is missing. Do NOT install an SSH server for this task.'
    Write-Host 'Use the official AutoDL Windows tunnel tool: https://www.autodl.com/docs/ssh_proxy/'
    Write-Host 'Or install OpenSSH Client in Windows Optional Features, reopen PowerShell and retry.'
    exit 2
}
if ($CheckOnly) {
    & $AaaSshExe -V
    Write-Host 'Read-only check complete; no connection or system setting was changed.'
    exit 0
}
if (-not $AaaSshHost) { $AaaSshHost=(Read-Host 'SSH HOST: paste only the host AFTER @ in your AutoDL SSH command').Trim() }
if (-not (Test-AaaHost $AaaSshHost)) { throw 'Invalid host. No URL, root@, port, whitespace or quotes; use your OWN instance host.' }
if ($AaaSshPort -eq 0) {
    $AaaPortText=(Read-Host 'SSH PORT: enter the number AFTER -p (do not press Enter on an empty field)').Trim()
    if (-not [int]::TryParse($AaaPortText,[ref]$AaaSshPort)) { throw 'Port must be a number; no connection was started.' }
}
if ($AaaSshPort -lt 1 -or $AaaSshPort -gt 65535) { throw 'Port must be 1..65535; no connection was started.' }
$AaaPorts=@($AstrBotLocalPort,$ComfyLocalPort,$HubLocalPort,$NapCatLocalPort)
if (($AaaPorts | Select-Object -Unique).Count -ne 4) { throw 'Local ports must be distinct.' }
Write-Host 'Keep this window open. A quiet window after SSH authentication is NORMAL.'
Write-Host 'Use your cloud instance SSH password, NOT the AstrBot password or any app token.'
Write-Host 'Verify a new host fingerprint through a trusted platform source. This tool does NOT bypass host checking.'
Write-Host ('AstrBot: http://127.0.0.1:{0}' -f $AstrBotLocalPort)
Write-Host ('ComfyUI: http://127.0.0.1:{0}' -f $ComfyLocalPort)
Write-Host ('Hub:     http://127.0.0.1:{0}' -f $HubLocalPort)
Write-Host ('NapCat:  http://127.0.0.1:{0}/webui' -f $NapCatLocalPort)
$AaaSshArgs=@('-N','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=30','-o','ServerAliveCountMax=3','-o','StrictHostKeyChecking=ask',
    '-L',('127.0.0.1:{0}:127.0.0.1:6185' -f $AstrBotLocalPort),
    '-L',('127.0.0.1:{0}:127.0.0.1:8188' -f $ComfyLocalPort),
    '-L',('127.0.0.1:{0}:127.0.0.1:6278' -f $HubLocalPort),
    '-L',('127.0.0.1:{0}:127.0.0.1:6099' -f $NapCatLocalPort),
    '-p',[string]$AaaSshPort,('root@'+$AaaSshHost))
& $AaaSshExe @AaaSshArgs
if ($LASTEXITCODE -ne 0) { Write-Host 'Tunnel ended with an SSH error. Read the SSH error; do not reset app credentials to repair a tunnel.' }
exit $LASTEXITCODE
