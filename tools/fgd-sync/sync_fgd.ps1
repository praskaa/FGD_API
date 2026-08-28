# sync_fgd.ps1 - One-way sync of shared tools from FGD_Tools.extension
# into PyPrasKaa.extension, with optional local auto-commit.
#
# Usage:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File sync_fgd.ps1 [-AutoCommit]
#
# -AutoCommit: stage ONLY the mapped Dst folders in PyPrasKaa and commit
#              "Sync from FGD @ <fgd_short_hash>" locally (no push).
#
# Root resolution (in priority order):
#   1. tools/fgd-sync/sync-config.json keys fgd_root / pypraskaa_root
#   2. Defaults: FGD root = repo root of this script;
#      PyPrasKaa root = ..\..\..\..\PyPrasKaa.extension (pyRevit layout).
#
# Every run is logged to tools/fgd-sync/sync.log. Failures are logged, never
# thrown, so a git post-commit hook calling this never blocks the commit.

param(
    [switch]$AutoCommit
)

$ErrorActionPreference = 'Continue'

$SCRIPT_DIR   = $PSScriptRoot
$LOG_PATH     = Join-Path $SCRIPT_DIR 'sync.log'
$CONFIG_PATH  = Join-Path $SCRIPT_DIR 'sync-config.json'

$FGD_ROOT_DEFAULT       = Split-Path (Split-Path $SCRIPT_DIR -Parent) -Parent
$PYPRASKAA_ROOT_DEFAULT = [System.IO.Path]::GetFullPath((Join-Path $SCRIPT_DIR '..\..\..\..\PyPrasKaa.extension'))

# ---------------------------------------------------------------------------
# Config (optional machine-specific overrides)
# ---------------------------------------------------------------------------
$FGD_ROOT       = $FGD_ROOT_DEFAULT
$PYPRASKAA_ROOT = $PYPRASKAA_ROOT_DEFAULT

if (Test-Path $CONFIG_PATH) {
    try {
        $cfg = Get-Content $CONFIG_PATH -Raw | ConvertFrom-Json
        if ($cfg.fgd_root)       { $FGD_ROOT = $cfg.fgd_root }
        if ($cfg.pypraskaa_root) { $PYPRASKAA_ROOT = $cfg.pypraskaa_root }
    } catch {
        Write-Host "[sync] WARN: could not parse $CONFIG_PATH - using defaults"
    }
}

# ---------------------------------------------------------------------------
# Mapping (FGD = source of truth -> PyPrasKaa)
# ---------------------------------------------------------------------------
$MAPPINGS = @(
    @{
        Src = 'FGD-API.tab/Tools.panel/Button Generator.pushbutton'
        Dst = 'PrasKaaPyKit.tab/Development.panel/Button Generator.pushbutton'
    },
    @{
        Src = 'FGD-API.tab/Tools.panel/ToolbarManager.pushbutton'
        Dst = 'PrasKaaPyKit.tab/Development.panel/Toolbar Manager.pushbutton'
    }
)

# Runtime state that must survive the mirror (excluded from copy AND purge)
$EXCLUDE_FILES = @('_settings.json')

# Stale artifacts in Dst side that mirroring cannot remove (untracked/gitignored)
$DST_EXTRA_CLEANUP = @('PrasKaaPyKit.tab/Development.panel/Toolbar Manager.pushbutton.zip')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Log($msg) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    try { Add-Content -Path $LOG_PATH -Value $line -Encoding UTF8 } catch { }
    Write-Output "[sync] $msg"
}

function Sync-Folder($src, $dst) {
    if (-not (Test-Path $src)) {
        Write-Log "SKIP source not found: $src"
        return
    }
    $dstParent = Split-Path $dst -Parent
    if (-not (Test-Path $dstParent)) {
        New-Item -ItemType Directory -Path $dstParent -Force | Out-Null
    }

    $roboArgs = @($src, $dst, '/MIR', '/NJH', '/NJS', '/NP', '/NDL', '/NFL')
    foreach ($f in $EXCLUDE_FILES) {
        $roboArgs += '/XF'
        $roboArgs += $f
    }
    & robocopy @roboArgs | Out-Null
    if ($LASTEXITCODE -ge 8) {
        Write-Log "ERROR robocopy failed ($LASTEXITCODE): $src -> $dst"
    } else {
        Write-Log "OK synced: $src -> $dst"
    }
    $LASTEXITCODE = 0
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
Write-Log "==== sync start (AutoCommit=$AutoCommit) ===="
Write-Log "FGD root:       $FGD_ROOT"
Write-Log "PyPrasKaa root: $PYPRASKAA_ROOT"

if (-not (Test-Path $FGD_ROOT)) {
    Write-Log "ERROR FGD root not found: $FGD_ROOT"
    exit 1
}
if (-not (Test-Path $PYPRASKAA_ROOT)) {
    Write-Log "ERROR PyPrasKaa root not found: $PYPRASKAA_ROOT"
    exit 1
}

foreach ($m in $MAPPINGS) {
    Sync-Folder (Join-Path $FGD_ROOT $m.Src) (Join-Path $PYPRASKAA_ROOT $m.Dst)
}

foreach ($rel in $DST_EXTRA_CLEANUP) {
    $p = Join-Path $PYPRASKAA_ROOT $rel
    if (Test-Path $p) {
        Remove-Item -Path $p -Recurse -Force
        Write-Log "CLEAN removed: $rel"
    }
}

if ($AutoCommit) {
    $pyGitDir = Join-Path $PYPRASKAA_ROOT '.git'
    if (-not (Test-Path $pyGitDir)) {
        Write-Log 'SKIP auto-commit: PyPrasKaa is not a git repo'
    } elseif ((Test-Path (Join-Path $pyGitDir 'MERGE_HEAD')) -or (Test-Path (Join-Path $pyGitDir 'REBASE_HEAD'))) {
        Write-Log 'SKIP auto-commit: merge/rebase in progress in PyPrasKaa'
    } else {
        Push-Location $PYPRASKAA_ROOT
        try {
            $fgdHash = (git -C $FGD_ROOT rev-parse --short HEAD 2>$null).Trim()
            foreach ($m in $MAPPINGS) {
                & git add -- $m.Dst
            }
            $staged = & git diff --cached --name-only
            if ($staged) {
                $msg = "Sync from FGD @ $fgdHash"
                & git commit -m $msg | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Write-Log "COMMIT $msg ($($staged.Count) file(s))"
                } else {
                    Write-Log "ERROR git commit failed: $msg"
                }
            } else {
                Write-Log 'INFO nothing staged - no commit needed'
            }
        } finally {
            Pop-Location
        }
    }
}

Write-Log '==== sync done ===='
