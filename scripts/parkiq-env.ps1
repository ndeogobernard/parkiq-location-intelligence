<#
Activate the ParkIQ environment in the CURRENT PowerShell session (dot-source it):

    . C:\GIS\ParkIQ\scripts\parkiq-env.ps1
    parkiq check-config --market markets\franklin_oh.yaml
    pytest

Why not `conda activate`? Other software on a workstation PATH can ship its own geos_c.dll /
spatialite.dll / libxml2.dll / ICU, and conda-forge Python may load those instead of the
environment's copies ("DLL load failed ... procedure could not be found"). This script puts the
environment first and keeps only Windows system folders and git for this session.
Nothing is changed permanently.
#>
param([string]$EnvPath = "C:\GIS\envs\parkiq")

if (-not (Test-Path (Join-Path $EnvPath "python.exe"))) {
    throw "ParkIQ env not found at $EnvPath. Create it: see README.md 'Install'."
}
$envDirs = @(
    $EnvPath,
    (Join-Path $EnvPath "Library\mingw-w64\bin"),
    (Join-Path $EnvPath "Library\usr\bin"),
    (Join-Path $EnvPath "Library\bin"),
    (Join-Path $EnvPath "Scripts"),
    (Join-Path $EnvPath "bin")
)
$system = @("$env:SystemRoot\System32", "$env:SystemRoot", "$env:SystemRoot\System32\WindowsPowerShell\v1.0",
            "$env:SystemRoot\System32\Wbem", "$env:SystemRoot\System32\OpenSSH")
$git = (Get-Command git -ErrorAction SilentlyContinue)
$gitDir = if ($git) { @(Split-Path $git.Source) } else { @() }
$ghDir = @(Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\GitHub.cli_*\bin", "$env:ProgramFiles\GitHub CLI" -Filter gh.exe -ErrorAction SilentlyContinue | Select-Object -First 1 | ForEach-Object { $_.DirectoryName })
$env:PATH = (($envDirs + $system + $gitDir + $ghDir) -join ";")
$env:GDAL_DATA = Join-Path $EnvPath "Library\share\gdal"
$env:PROJ_DATA = Join-Path $EnvPath "Library\share\proj"
$env:PROJ_LIB = $env:PROJ_DATA
$env:CONDA_PREFIX = $EnvPath
Write-Host "ParkIQ env active: $EnvPath (python $(& python -c 'import sys;print(sys.version.split()[0])'))"
# Pick up API keys (Census, CTPP) from the user environment if this window predates them
# (never printed).
foreach ($n in @("CENSUS_API_KEY", "CTPP_API_KEY")) {
    if (-not [Environment]::GetEnvironmentVariable($n, "Process")) {
        $k = [Environment]::GetEnvironmentVariable($n, "User")
        if ($k) { [Environment]::SetEnvironmentVariable($n, $k, "Process") }
        Remove-Variable k -ErrorAction SilentlyContinue
    }
}
