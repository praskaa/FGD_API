# install-hooks.ps1 - Installs a post-commit hook in the FGD repo that
# auto-syncs the shared tools into PyPrasKaa after every FGD commit.
#
# Usage:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File install-hooks.ps1

$FGD_ROOT  = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$HooksDir  = Join-Path $FGD_ROOT '.git\hooks'
$HookPath  = Join-Path $HooksDir 'post-commit'

if (-not (Test-Path $HooksDir)) {
    Write-Host "[install-hooks] ERROR: $HooksDir not found - is $FGD_ROOT a git repo?" -ForegroundColor Red
    exit 1
}

$HookContent = @'
#!/bin/sh
# post-commit - auto-sync FGD tools into PyPrasKaa (installed by install-hooks.ps1)
REPO_ROOT=$(git rev-parse --show-toplevel)
SYNC_SCRIPT="$REPO_ROOT/tools/fgd-sync/sync_fgd.ps1"
if [ -f "$SYNC_SCRIPT" ]; then
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$SYNC_SCRIPT" -AutoCommit >> /dev/null 2>&1
fi
'@

# ASCII, no BOM: a UTF-8 BOM breaks the #!/bin/sh shebang under Git for Windows.
[System.IO.File]::WriteAllText($HookPath, $HookContent, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[install-hooks] OK: post-commit hook installed at $HookPath" -ForegroundColor Green
Write-Host "[install-hooks] FGD commits will now auto-sync into PyPrasKaa (quiet, logged to tools/fgd-sync/sync.log)."
