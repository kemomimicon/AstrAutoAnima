# ASCII-only bootstrap for Windows PowerShell 5.1 legacy code pages.
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$releaseRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $releaseRoot

function Find-ProjectPython {
    # PS 5.1 turns native stderr into a terminating error under Stop, even with
    # 2>$null. Missing Tk / missing py -3.12 is an expected probe failure.
    $probePreference = $ErrorActionPreference
    try {
    $ErrorActionPreference = 'Continue'
    foreach ($candidate in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", 'python', 'python3')) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found -and $found.Source -notlike '*WindowsApps*') {
            & $found.Source -c 'import sys,tkinter; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { return $found.Source }
        }
    }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $answer = & $launcher.Source -3.12 -c 'import sys,tkinter; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $answer -and (Test-Path -LiteralPath "$answer" -PathType Leaf)) { return "$answer" }
    }
    return $null
    } finally {
        $ErrorActionPreference = $probePreference
    }
}

Write-Host '[AAA bootstrap 1/3] Checking Python 3.12 and Tk...'
Write-Progress -Activity 'AAA launcher preparation (not project installation)' -Status 'Checking Python 3.12 and Tk' -PercentComplete 10
$projectPython = Find-ProjectPython
if (-not $projectPython) {
    Add-Type -AssemblyName System.Windows.Forms
    $reply = [System.Windows.Forms.MessageBox]::Show('Python 3.12 with Tk is required. Install official Python via winget? No models will be downloaded.', 'AAA environment setup', 'YesNo')
    if ($reply -ne 'Yes') { throw 'Cancelled. Install Python 3.12 with Tcl/Tk and retry.' }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'winget missing. Install Python 3.12 from https://www.python.org/downloads/' }
    Write-Host '[AAA bootstrap] Installing Python. Keep this window open; winget output follows.'
    Write-Progress -Activity 'AAA launcher preparation (not project installation)' -Status 'Installing Python via winget; waiting for completion' -PercentComplete 25
    & winget install --id Python.Python.3.12 --exact --source winget --accept-package-agreements --accept-source-agreements --scope user
    if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
    $projectPython = Find-ProjectPython
    if (-not $projectPython) { throw 'Python not detected. Reopen this launcher after installation.' }
}

Write-Host '[AAA bootstrap 2/3] Checking optional Git...'
Write-Progress -Activity 'AAA launcher preparation (not project installation)' -Status 'Checking optional Git' -PercentComplete 60
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    $gitPath = Join-Path $env:ProgramFiles 'Git\cmd'
    if (Test-Path -LiteralPath (Join-Path $gitPath 'git.exe')) { $env:PATH = "$gitPath;$env:PATH" }
    else {
        Add-Type -AssemblyName System.Windows.Forms
        $reply = [System.Windows.Forms.MessageBox]::Show('New ComfyUI / node downloads need Git. Install Git via winget? No allows existing environments.', 'Optional Git', 'YesNo')
        if ($reply -eq 'Yes') {
            if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'winget missing. Install Git from https://git-scm.com/downloads' }
            Write-Host '[AAA bootstrap] Installing Git. Keep this window open; winget output follows.'
            & winget install --id Git.Git --exact --source winget --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) { throw 'Git installation failed.' }
            if (Test-Path -LiteralPath $gitPath) { $env:PATH = "$gitPath;$env:PATH" }
        }
    }
}
Write-Host '[AAA bootstrap 3/3] Opening setup center. Choose deployment to see project stage lights and progress.'
Write-Progress -Activity 'AAA launcher preparation (not project installation)' -Completed
& $projectPython (Join-Path $PSScriptRoot 'setup_center.py') --platform windows
if ($LASTEXITCODE -ne 0) { throw 'Deployment incomplete. Read the error above.' }
