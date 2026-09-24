<#
Rebuild the local ArcGIS Pro workspace (arcgis\ParkIQ_Workspace.aprx) from the run folders.
Close the project in ArcGIS Pro first.

    C:\GIS\ParkIQ\scripts\refresh-aprx.ps1            # latest 2 runs per market
    C:\GIS\ParkIQ\scripts\refresh-aprx.ps1 -All       # every run
    C:\GIS\ParkIQ\scripts\refresh-aprx.ps1 -Open      # rebuild, then open in ArcGIS Pro
#>
param([switch]$All, [int]$Latest = 2, [switch]$Open)

$pro = "C:\Program Files\ArcGIS\Pro"
$py = Join-Path $pro "bin\Python\envs\arcgispro-py3\python.exe"
$repo = Split-Path $PSScriptRoot -Parent
$argsList = @((Join-Path $repo "arcgis\build_workspace.py"))
if ($All) { $argsList += "--all" } else { $argsList += @("--latest", $Latest) }
& $py @argsList
if ($LASTEXITCODE -eq 0 -and $Open) {
    Start-Process (Join-Path $repo "arcgis\ParkIQ_Workspace.aprx")
}
