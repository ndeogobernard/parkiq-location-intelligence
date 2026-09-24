# Source from Git Bash:  source /c/GIS/ParkIQ/scripts/parkiq-env.sh
# Same purpose as parkiq-env.ps1 (clean PATH so third-party DLLs on PATH don't shadow the env's).
E="${PARKIQ_ENV:-/c/GIS/envs/parkiq}"
export PATH="$E:$E/Library/mingw-w64/bin:$E/Library/usr/bin:$E/Library/bin:$E/Scripts:$E/bin:/c/Windows/System32:/c/Windows:/c/Windows/System32/WindowsPowerShell/v1.0:/mingw64/bin:/usr/bin"
export GDAL_DATA="$(cygpath -w "$E/Library/share/gdal")"
export PROJ_DATA="$(cygpath -w "$E/Library/share/proj")"
export PROJ_LIB="$PROJ_DATA"
export CONDA_PREFIX="$(cygpath -w "$E")"
export PYTHONIOENCODING=utf-8
# User-level environment variables set after this app/shell started are not inherited; read the
# Census key from the user environment into this session only (never printed or written).
if [ -z "${CENSUS_API_KEY:-}" ]; then
  _k=$(powershell.exe -NoProfile -Command "[Environment]::GetEnvironmentVariable('CENSUS_API_KEY','User')" 2>/dev/null | tr -d '\r\n')
  if [ -n "$_k" ]; then export CENSUS_API_KEY="$_k"; fi
  unset _k
fi
