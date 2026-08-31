# FGD_API Extension Updater — Implementation Plan

## Overview

Create a pyRevit pushbutton script (`ExtensionUpdater.pushbutton`) inside the `Tools.panel` that updates the FGD_API extension by pulling the latest changes from GitHub, while preserving the `Sandbox.panel` folder and `lib/` directory.

## Architecture

### Location
- **Script path**: `FGD-API.tab/Tools.panel/ExtensionUpdater.pushbutton/`
- **Files to create**:
  - `script.py` — Main updater logic
  - `bundle.yaml` — pyRevit button metadata
  - `icon.png` — Button icon (reuse from Button Generator or create simple one)

### Core Logic Flow

```
1. Detect extension root path (from script location)
2. Confirm with user (pyRevit forms.alert)
3. Create backup of entire extension (zip in parent dir with timestamp)
4. Preserve Sandbox.panel (move to temp location)
5. Preserve lib/ folder (move to temp location)
6. Run `git pull origin main` (or master) in extension root
7. Restore Sandbox.panel from temp
8. Restore lib/ from temp
9. Show result report
10. Trigger pyRevit reload
```

## Detailed Implementation

### Step 1: Path Detection
- Use the same pattern as existing scripts: derive `EXTENSION_ROOT` from `__file__` location
- Script lives at: `<EXTENSION_ROOT>/FGD-API.tab/Tools.panel/ExtensionUpdater.pushbutton/script.py`
- Go up 3 levels to get extension root

### Step 2: User Confirmation
- Use `pyrevit.forms.ask_yes_no()` to confirm before proceeding
- Show warning about the process: backup → pull → restore

### Step 3: Backup
- Create timestamped zip: `FGD_Tools_backup_YYYYMMDD_HHMMSS.zip` in parent of extension root
- Use `shutil.make_archive()` (available in IronPython stdlib)
- Include entire extension directory contents

### Step 4-5: Preserve Protected Folders
- Define protected paths:
  - `Sandbox.panel` → `<EXTENSION_ROOT>/FGD-API.tab/Sandbox.panel/`
  - `lib/` → `<EXTENSION_ROOT>/lib/`
- Move each to a temp directory (`%TEMP%/fgd_update_tmp/`) using `shutil.move()`
- Track which ones existed (Sandbox might not exist yet)

### Step 6: Git Pull
- Use `subprocess` to run: `git -C <EXTENSION_ROOT> pull origin main`
- Fallback: try `master` branch if `main` fails
- Capture stdout/stderr for reporting
- Handle cases:
  - Already up to date
  - Merge conflicts (report and abort)
  - Network errors (report and abort)
  - Git not found (report and abort)

### Step 7-8: Restore Protected Folders
- Move preserved folders back from temp to original locations
- If folder now exists from git pull (e.g., Sandbox.panel was added to repo), keep the preserved version (don't overwrite)
- Clean up temp directory

### Step 9: Report
- Use `script.get_output()` to print formatted report
- Show: backup location, git output, restored folders, any warnings

### Step 10: Reload
- Call `pyrevit.loader.sessionmgr.reload_pyrevit()` to refresh

## Edge Cases & Error Handling

| Scenario | Handling |
|----------|----------|
| Sandbox.panel doesn't exist | Skip preservation, note in report |
| lib/ doesn't exist (unlikely) | Skip preservation, note in report |
| Git pull fails | Restore preserved folders from temp, abort with error |
| Backup fails | Ask user to continue or abort |
| Extension not a git repo | Error: "Extension directory is not a git repository" |
| Network unavailable | Error with clear message |
| Git not in PATH | Error: "git command not found" |

## bundle.yaml Content

```yaml
title: Extension
tooltip: Update FGD_API extension from GitHub (preserves Sandbox.panel and lib/)
author: PrasKaa
```

## Dependencies (all available in IronPython/pyRevit)
- `os`, `shutil`, `subprocess`, `datetime` — stdlib
- `pyrevit.forms` — user confirmation and alerts
- `pyrevit.script` — output reporting
- `pyrevit.loader.sessionmgr` — pyRevit reload

## Files to Create

1. `FGD-API.tab/Tools.panel/ExtensionUpdater.pushbutton/bundle.yaml`
2. `FGD-API.tab/Tools.panel/ExtensionUpdater.pushbutton/script.py`
3. `FGD-API.tab/Tools.panel/ExtensionUpdater.pushbutton/icon.png` (copy from Button Generator or skip — pyRevit will use default)

## Validation

1. Run `script.py` syntax check via `python -m py_compile` (if possible with IronPython compat)
2. Verify the pushbutton appears in pyRevit ribbon under FGD-API → Tools
3. Test in a safe environment: clone repo to temp dir, create dummy Sandbox.panel + lib/, run updater, verify preservation
4. Verify backup zip is created correctly
5. Verify git pull works and report is accurate
