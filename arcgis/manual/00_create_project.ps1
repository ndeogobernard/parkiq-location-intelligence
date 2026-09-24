<#
ParkIQ - Franklin County, OH - Session 1: create the local project folder + git repo.
Run in PowerShell:
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\00_create_project.ps1 -Root "C:\GIS\ParkIQ_FranklinOH"
Safe to re-run (existing folders/files are left alone).
#>
param([string]$Root = "C:\GIS\ParkIQ_FranklinOH")

$dirs = @(
  "00_admin", "00_admin\run_logs",
  "01_raw\S00_boundary", "01_raw\S01_parcels", "01_raw\S01b_cama", "01_raw\S02_S03_overture",
  "01_raw\S03_S06_S08_osm", "01_raw\S04_lodes", "01_raw\S05_acs", "01_raw\S07_rate_survey",
  "01_raw\S09_gtfs", "01_raw\S10_venues", "01_raw\S12_hospitals_ipeds", "01_raw\S13_aadt",
  "01_raw\S14_fema", "01_raw\S15_epa", "01_raw\S18_dem", "01_raw\S20_S24_columbus",
  "02_working", "03_tables", "04_excel", "05_maps\drafts", "05_maps\final",
  "06_package", "docs", "scripts", "portfolio\images"
)
foreach ($d in $dirs) { New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null }

$gitignore = @"
# --- data & large outputs: never commit ---
01_raw/
02_working/
03_tables/
06_package/
*.gdb/
*.gpkg
*.tif
*.zip
*.lock
.backups/
~`$*.xlsx
# --- ArcGIS Pro clutter ---
*.atbx.bak
Index/
ImportLog/
GpMessages/
# --- python ---
__pycache__/
*.pyc
.venv/
"@
$gi = Join-Path $Root ".gitignore"
if (-not (Test-Path $gi)) { Set-Content -Path $gi -Value $gitignore -Encoding UTF8 }

$readme = @"
# ParkIQ - Surface-Lot Parking Site Selection: Franklin County, OH (pilot)

Where a paid surface parking lot fills across dayparts and pays: a location-intelligence and
investment-underwriting study for Franklin County, Ohio.

- Method: docs/SCOPE.md, docs/MANUAL_METHODOLOGY.md
- Admin (parameters, sources, decisions, QA): 00_admin/ParkIQ_FranklinOH_Admin.xlsx
- Scripts: scripts/
- Status: Session 1 - project setup

Raw data and working geodatabases are not committed (see .gitignore); every source is listed
in the Source Register with URL, vintage and download date so the work is reproducible.
"@
$rm = Join-Path $Root "README.md"
if (-not (Test-Path $rm)) { Set-Content -Path $rm -Value $readme -Encoding UTF8 }

if (Get-Command git -ErrorAction SilentlyContinue) {
  Push-Location $Root
  if (-not (Test-Path ".git")) { git init | Out-Null; Write-Host "git repo initialised" }
  Pop-Location
} else { Write-Host "git not found - install Git for Windows, then run 'git init' in $Root" }

Write-Host "Project folder ready: $Root"
