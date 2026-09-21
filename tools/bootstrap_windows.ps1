$ErrorActionPreference = 'Stop'
$releaseRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $releaseRoot

function Find-ProjectPython {
    foreach ($candidate in @('python', 'python3', "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) {
            & $found.Source -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { return $found.Source }
        }
    }
    return $null
}

$projectPython = Find-ProjectPython
if (-not $projectPython) {
    Add-Type -AssemblyName System.Windows.Forms
    $reply = [System.Windows.Forms.MessageBox]::Show('未找到 Python 3.12+。是否允许通过 winget 安装官方 Python 3.12？这是外部下载，不会安装模型。', '首次环境准备', 'YesNo')
    if ($reply -ne 'Yes') { throw '已取消。可自行安装 Python 3.12 后重试。' }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw '系统缺少 winget。请从 https://www.python.org/downloads/ 安装 Python 3.12，并启用 Tcl/Tk。' }
    & winget install --id Python.Python.3.12 --exact --source winget --accept-package-agreements --accept-source-agreements --scope user
    if ($LASTEXITCODE -ne 0) { throw 'Python 安装失败，停止部署。' }
    $projectPython = Find-ProjectPython
    if (-not $projectPython) { throw '请重新打开部署入口以加载 Python 路径。' }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    $gitPath = Join-Path $env:ProgramFiles 'Git\cmd'
    if (Test-Path -LiteralPath (Join-Path $gitPath 'git.exe')) { $env:PATH = "$gitPath;$env:PATH" }
    else {
        Add-Type -AssemblyName System.Windows.Forms
        $reply = [System.Windows.Forms.MessageBox]::Show('下载全新 ComfyUI 和外部节点需要 Git。是否通过 winget 安装官方 Git？选“否”仍可接入已有环境。', '可选环境准备', 'YesNo')
        if ($reply -eq 'Yes') {
            & winget install --id Git.Git --exact --source winget --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) { throw 'Git 安装失败，停止部署。' }
            if (Test-Path -LiteralPath $gitPath) { $env:PATH = "$gitPath;$env:PATH" }
        }
    }
}
& $projectPython (Join-Path $PSScriptRoot 'deploy_project.py')
if ($LASTEXITCODE -ne 0) { throw '部署未完成，请查看上方错误信息。' }
