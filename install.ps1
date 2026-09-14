$ErrorActionPreference = "Stop"
$Repo = $PSScriptRoot
$Package = Join-Path $Repo "howto"

Write-Host "howto"
if (Get-Command pipx -ErrorAction SilentlyContinue) {
    pipx install --force $Package
} else {
    $Python = Get-Command python -ErrorAction SilentlyContinue
    $PythonArgs = @()
    if (-not $Python) {
        $Python = Get-Command py -ErrorAction Stop
        $PythonArgs = @("-3")
    }
    $Venv = Join-Path $env:LOCALAPPDATA "agentrc\howto"
    & $Python.Source @PythonArgs -m venv $Venv
    & (Join-Path $Venv "Scripts\python.exe") -m pip install --upgrade $Package
    Write-Host "installed howto in $Venv"
    Write-Host "add $(Join-Path $Venv 'Scripts') to PATH if `howto` is not found"
}
