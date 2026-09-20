<#
.SYNOPSIS
  Copy the code to the NAS project folder, check every file arrived intact, and (optionally)
  ask the running app whether it is on the same build.

.EXAMPLE
  .\scripts\deploy_nas.ps1 -Target \\NAS\docker\PartsNAS
  .\scripts\deploy_nas.ps1 -Target \\NAS\docker\PartsNAS -Url http://your-nas:8770

  Copies code only. data\ is never touched, and nothing on the target is deleted.
  After the copy: Container Manager -> delete the project's container and image, then create
  it again (Start alone re-uses the old image). -Url can then confirm the build id matches.
#>
param(
  [Parameter(Mandatory)][string]$Target,
  [string]$Url
)
$ErrorActionPreference = "Stop"
$src = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $Target)) { throw "Target not found: $Target" }

robocopy $src $Target /E /NJH /NJS /NDL /NP /XD data .venv .git __pycache__ .claude snapshot node_modules tests /XF *.pyc .gitignore | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed (exit $LASTEXITCODE)" }

$skip = '\\(\.venv|\.git|data|__pycache__|\.claude|snapshot|node_modules|tests)\\'
$n = 0; $bad = 0
Get-ChildItem -LiteralPath $src -Recurse -File -Force |
  Where-Object { $_.FullName -notmatch $skip -and $_.Name -ne ".gitignore" -and $_.Extension -ne ".pyc" } |
  ForEach-Object {
    $rel = $_.FullName.Substring($src.Length + 1); $n++
    if ((Get-FileHash -LiteralPath $_.FullName).Hash -ne (Get-FileHash -LiteralPath (Join-Path $Target $rel)).Hash) { $bad++; "DIFFERENT: $rel" }
  }
"Copied and checked $n files, $bad different."
if ($bad) { exit 1 }

$py = Join-Path $src ".venv\Scripts\python.exe"
if (Test-Path $py) {
  Push-Location (Join-Path $src "backend")
  $local = & $py -c "from app.buildid import build_id; print(build_id())"
  Pop-Location
  "Build id of this code: $local"
  if ($Url) {
    try {
      $h = Invoke-RestMethod "$Url/api/health"
      if ($h.build -eq $local) { "Running app: build $($h.build) - it runs this code." }
      else { "Running app: build $($h.build) - NOT this code yet. Rebuild it (delete the container + image, create again)." }
    } catch { "Could not reach $Url : $($_.Exception.Message)" }
  }
}
