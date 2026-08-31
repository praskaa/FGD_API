# -*- coding: utf-8 -*-
title = "Extension\nUpdater"
doc = """Version = 1.0
Date    = 31.08.2026

Description:
Update FGD_API extension from GitHub. Pulls the latest changes
while preserving the Sandbox.panel folder and lib/ directory.

How-To:
1. Click to run the updater.
2. Confirm the action.
3. Script will backup, pull, restore protected folders, and reload.

Last Updates:
- [31.08.2026] v1.0 Initial release.

Author: PrasKaa"""

import os
import sys
import shutil
import subprocess
import tempfile
import datetime

from pyrevit import forms, script
from pyrevit.loader import sessionmgr


REPO_URL = "https://github.com/praskaa/FGD_API"
GIT_PULL_TIMEOUT = 120


def find_git():
    """Locate git.exe: check PATH first, then common Windows install locations."""
    # Check PATH
    for path_dir in os.environ.get('PATH', '').split(os.pathsep):
        git_exe = os.path.join(path_dir, 'git.exe')
        if os.path.isfile(git_exe):
            return 'git'
    # Common Windows install locations
    candidates = [
        r'C:\Program Files\Git\bin\git.exe',
        r'C:\Program Files (x86)\Git\bin\git.exe',
        r'C:\Users\{}\AppData\Local\GitHub\PortableGit*\cmd\git.exe'.format(
            os.environ.get('USERNAME', '')),
        r'C:\ProgramData\GitHub\PortableGit*\cmd\git.exe',
    ]
    import glob
    for pattern in candidates:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None


def get_extension_root():
    path_script = os.path.abspath(__file__)
    path_pushbutton = os.path.dirname(path_script)
    path_panel = os.path.dirname(path_pushbutton)
    path_tab = os.path.dirname(path_panel)
    path_root = os.path.dirname(path_tab)
    return path_root


def is_git_repo(repo_path):
    git_dir = os.path.join(repo_path, '.git')
    return os.path.isdir(git_dir)


def create_backup(repo_path, backup_dir):
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    ext_name = os.path.basename(repo_path)
    backup_name = '{}_backup_{}'.format(ext_name, timestamp)
    backup_path = os.path.join(backup_dir, backup_name)
    shutil.make_archive(backup_path, 'zip', repo_path)
    return backup_path + '.zip'


def preserve_folders(repo_path, temp_dir):
    tab_dir = os.path.join(repo_path, 'FGD-API.tab')
    sandbox_path = os.path.join(tab_dir, 'Sandbox.panel')
    lib_path = os.path.join(repo_path, 'lib')
    preserved = {}
    if os.path.isdir(sandbox_path):
        dest = os.path.join(temp_dir, 'Sandbox.panel')
        shutil.move(sandbox_path, dest)
        preserved['Sandbox.panel'] = dest
    if os.path.isdir(lib_path):
        dest = os.path.join(temp_dir, 'lib')
        shutil.move(lib_path, dest)
        preserved['lib'] = dest
    return preserved


def restore_folders(repo_path, preserved, temp_dir):
    tab_dir = os.path.join(repo_path, 'FGD-API.tab')
    restored = []
    warnings = []
    for name, temp_path in preserved.items():
        if name == 'Sandbox.panel':
            dest = os.path.join(tab_dir, 'Sandbox.panel')
        else:
            dest = os.path.join(repo_path, name)
        if os.path.isdir(dest):
            warnings.append('  [WARN] {} already exists after pull — kept preserved version'.format(name))
            shutil.rmtree(dest)
        shutil.move(temp_path, dest)
        restored.append(name)
    return restored, warnings


def run_git_pull(repo_path):
    git_exe = find_git()
    if not git_exe:
        return False, '', (
            'git.exe not found.\n\n'
            'Please install Git for Windows from https://git-scm.com/download/win\n'
            'or make sure git is in your system PATH.'
        )
    branches = ['main', 'master']
    last_error = None
    for branch in branches:
        try:
            proc = subprocess.Popen(
                [git_exe, '-C', repo_path, 'pull', 'origin', branch],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False
            )
            try:
                stdout, stderr = proc.communicate(timeout=GIT_PULL_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return False, 'Git pull timed out after {} seconds'.format(GIT_PULL_TIMEOUT), ''
            stdout = stdout.decode('utf-8', errors='replace') if stdout else ''
            stderr = stderr.decode('utf-8', errors='replace') if stderr else ''
            if proc.returncode == 0:
                return True, stdout, stderr
            else:
                last_error = (proc.returncode, stdout, stderr)
        except OSError as e:
            return False, '', 'git command not found: {}'.format(e)
    if last_error:
        code, out, err = last_error
        return False, out, err
    return False, '', 'No branches matched (tried: {})'.format(', '.join(branches))


def main():
    output = script.get_output()
    output.close_others()

    repo_path = get_extension_root()

    output.print_md('## FGD_API Extension Updater')
    output.print_md('**Extension path:** `{}`'.format(repo_path))
    output.print_md('---')

    if not is_git_repo(repo_path):
        forms.alert(
            'Extension directory is not a git repository.\n\n'
            'Please clone {} into the extension folder first.'.format(REPO_URL),
            title='Updater Error',
            exitscript=True
        )

    confirm = forms.alert(
        'This will update the FGD_API extension from GitHub.\n\n'
        'Process:\n'
        '1. Create a backup (zip)\n'
        '2. Preserve Sandbox.panel and lib/\n'
        '3. Pull latest changes from GitHub\n'
        '4. Restore preserved folders\n'
        '5. Reload pyRevit\n\n'
        'Continue?',
        title='Extension Updater',
        yes=True,
        no=True
    )

    if not confirm:
        script.exit()

    temp_dir = tempfile.mkdtemp(prefix='fgd_update_')
    backup_path = None
    preserved = {}
    warnings = []

    try:
        output.print_md('### Creating backup...')
        backup_dir = os.path.dirname(repo_path)
        try:
            backup_path = create_backup(repo_path, backup_dir)
            output.print_md('  [OK] Backup: `{}`'.format(os.path.basename(backup_path)))
        except Exception as e:
            cont = forms.alert(
                'Backup failed:\n{}\n\nContinue without backup?'.format(e),
                title='Backup Warning',
                yes=True,
                no=True
            )
            if not cont:
                script.exit()

        output.print_md('### Preserving protected folders...')
        preserved = preserve_folders(repo_path, temp_dir)
        if preserved:
            for name in preserved:
                output.print_md('  [OK] Preserved: {}'.format(name))
        else:
            output.print_md('  [INFO] No protected folders found (Sandbox.panel / lib/)')

        output.print_md('### Pulling from GitHub...')
        success, stdout, stderr = run_git_pull(repo_path)

        if not success:
            error_msg = stderr or stdout or 'Unknown git error'
            output.print_md('  [FAIL] Git pull failed:')
            output.print_md('```\n{}\n```'.format(error_msg.strip()))
            raise RuntimeError('Git pull failed')

        git_output = stdout.strip()
        if git_output:
            for line in git_output.split('\n'):
                output.print_md('  {}'.format(line))

        if 'Already up to date' in git_output or 'Already up-to-date' in git_output:
            output.print_md('  [INFO] Already up to date — no changes pulled.')
        else:
            output.print_md('  [OK] Pull successful.')

        output.print_md('### Restoring protected folders...')
        restored, warnings = restore_folders(repo_path, preserved, temp_dir)
        if restored:
            for name in restored:
                output.print_md('  [OK] Restored: {}'.format(name))
        else:
            output.print_md('  [INFO] Nothing to restore.')

        if warnings:
            output.print_md('### Warnings')
            for w in warnings:
                output.print_md(w)

        output.print_md('---')
        output.print_md('### Update Complete')
        if backup_path:
            output.print_md('Backup saved at: `{}`'.format(backup_path))

        output.print_md('Reloading pyRevit...')
        sessionmgr.reload_pyrevit()

    except RuntimeError:
        if preserved:
            output.print_md('### Restoring preserved folders after failure...')
            try:
                restore_folders(repo_path, preserved, temp_dir)
                output.print_md('  [OK] Restored preserved folders.')
            except Exception as e:
                output.print_md('  [ERR] Could not restore: {}'.format(e))
                output.print_md('  Temp folder: `{}`'.format(temp_dir))
        forms.alert(
            'Update failed. Your files are safe — preserved folders have been restored.\n\n'
            'Backup: {}'.format(backup_path or 'N/A'),
            title='Update Failed'
        )
    except Exception as e:
        if preserved:
            output.print_md('### Restoring preserved folders after error...')
            try:
                restore_folders(repo_path, preserved, temp_dir)
                output.print_md('  [OK] Restored preserved folders.')
            except Exception as re:
                output.print_md('  [ERR] Could not restore: {}'.format(re))
                output.print_md('  Temp folder: `{}`'.format(temp_dir))
        forms.alert(
            'Unexpected error: {}\n\nPreserved folders restored.'.format(e),
            title='Update Error'
        )
    finally:
        if os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass


if __name__ == '__main__':
    main()
