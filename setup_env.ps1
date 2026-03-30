# Setup Python venv for pr_tracker on Windows
$ErrorActionPreference = "Stop"

$venvDir = Join-Path $PSScriptRoot ".venv"

# Find a real Python 3 interpreter (skip the Windows Store stub)
$pythonExe = $null
$pyArgs = @()
foreach ($candidate in @("python3", "python")) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found -and $found.Source -notlike "*WindowsApps*") {
        $pythonExe = $found.Source
        break
    }
}
# Fall back to the py launcher
if (-not $pythonExe) {
    $found = Get-Command py -ErrorAction SilentlyContinue
    if ($found) {
        $pythonExe = $found.Source
        $pyArgs = @("-3")
    }
}
if (-not $pythonExe) {
    Write-Host "Could not find Python 3. Please install Python 3.10+ and try again." -ForegroundColor Red
    exit 1
}

Write-Host "Using Python: $pythonExe $pyArgs" -ForegroundColor Cyan

if (-not (Test-Path $venvDir)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    & $pythonExe @pyArgs -m venv $venvDir
} else {
    Write-Host "Virtual environment already exists." -ForegroundColor Green
}

# Initialize comfy-runner submodule if present
$submoduleDir = Join-Path $PSScriptRoot "comfy-runner"
if (Test-Path (Join-Path $PSScriptRoot ".gitmodules")) {
    if (-not (Test-Path (Join-Path $submoduleDir "comfy_runner"))) {
        Write-Host "Initializing comfy-runner submodule..." -ForegroundColor Cyan
        git -C $PSScriptRoot submodule update --init --recursive
    }
}

Write-Host "Installing dependencies..." -ForegroundColor Cyan
& "$venvDir\Scripts\pip.exe" install --quiet -r "$PSScriptRoot\requirements.txt"

# Also install comfy-runner deps if submodule is present
$crReqs = Join-Path $submoduleDir "requirements.txt"
if (Test-Path $crReqs) {
    Write-Host "Installing comfy-runner dependencies..." -ForegroundColor Cyan
    & "$venvDir\Scripts\pip.exe" install --quiet -r $crReqs
}

# Link comfy-runner into venv so 'import comfy_runner' works
$sitePackages = & "$venvDir\Scripts\python.exe" -c "import site; print(site.getsitepackages()[0])"
$pthFile = Join-Path $sitePackages "comfy-runner.pth"
# Prefer workspace-level comfy-runner (sibling dir) over submodule
$wsRunner = Join-Path (Split-Path $PSScriptRoot -Parent) "comfy-runner"
if (Test-Path (Join-Path $wsRunner "comfy_runner")) {
    $linkTarget = (Resolve-Path $wsRunner).Path
} elseif (Test-Path (Join-Path $submoduleDir "comfy_runner")) {
    $linkTarget = (Resolve-Path $submoduleDir).Path
} else {
    $linkTarget = $null
}
if ($linkTarget) {
    Set-Content -Path $pthFile -Value $linkTarget -NoNewline
    Write-Host "Linked comfy-runner into venv: $linkTarget" -ForegroundColor Green
}

Write-Host ""
Write-Host "Setup complete. Run the tracker with:" -ForegroundColor Green
Write-Host '  $env:GITHUB_TOKEN = (Get-Content githubtoken.txt -Raw).Trim()' -ForegroundColor Yellow
Write-Host "  .venv\Scripts\python.exe pr_tracker.py --fast" -ForegroundColor Yellow
