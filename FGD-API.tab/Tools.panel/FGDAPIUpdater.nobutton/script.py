# -*- coding: utf-8 -*-
title = "Extension\nUpdater"
doc = """Version = 1.2
Date    = 31.08.2026

Description:
Update FGD_API extension from GitHub via REST API (no git required).
Preserves Sandbox.panel and lib/ directory during update.

How-To:
1. Click to run the updater.
2. Confirm the action.
3. Script will backup, download, restore protected folders, and reload.

Last Updates:
- [31.08.2026] v1.2 Adopted proven HTTP approach from Sync with GitHub script.
- [31.08.2026] v1.1 Switched to GitHub REST API.
- [31.08.2026] v1.0 Initial release.

Author: PrasKaa"""

import os
import json
import base64
import shutil
import tempfile
import datetime

import clr
clr.AddReference("System")
clr.AddReference("System.Net")

from System.Net import HttpWebRequest, WebException, ServicePointManager, SecurityProtocolType
from System.Text import Encoding
from System.IO import StreamReader

ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12

from pyrevit import forms, script
from pyrevit.loader import sessionmgr


REPO_OWNER = "praskaa"
REPO_NAME  = "FGD_API"
BRANCH     = "main"
API_BASE   = "https://api.github.com"


def get_extension_root():
    path_script = os.path.abspath(__file__)
    path_pushbutton = os.path.dirname(path_script)
    path_panel = os.path.dirname(path_pushbutton)
    path_tab = os.path.dirname(path_panel)
    path_root = os.path.dirname(path_tab)
    return path_root


def create_backup(repo_path, backup_dir):
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    ext_name = os.path.basename(repo_path)
    backup_name = '{}_backup_{}'.format(ext_name, timestamp)
    backup_path = os.path.join(backup_dir, backup_name)
    shutil.make_archive(backup_path, 'zip', repo_path)
    return backup_path + '.zip'


def preserve_folders(repo_path, temp_dir):
    """Move protected folders to temp before download."""
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
    """Restore protected folders from temp, overwriting downloaded versions."""
    tab_dir = os.path.join(repo_path, 'FGD-API.tab')
    restored = []
    warnings = []
    for name, temp_path in preserved.items():
        if name == 'Sandbox.panel':
            dest = os.path.join(tab_dir, 'Sandbox.panel')
        else:
            dest = os.path.join(repo_path, name)
        if os.path.isdir(dest):
            warnings.append('  [WARN] {} exists in both local and remote — kept local version'.format(name))
            shutil.rmtree(dest)
        shutil.move(temp_path, dest)
        restored.append(name)
    return restored, warnings


def api_request(method, endpoint, body=None):
    """Make a GitHub API request (public repos don't need auth)."""
    url = "{}/{}".format(API_BASE, endpoint.lstrip("/"))
    req = HttpWebRequest.Create(url)
    req.Method = method
    req.ContentType = "application/json"
    req.Accept = "application/vnd.github+json"
    req.Headers.Add("X-GitHub-Api-Version", "2022-11-28")
    req.UserAgent = "FGD-API-Updater-pyRevit"

    if body is not None:
        body_bytes = Encoding.UTF8.GetBytes(json.dumps(body))
        req.ContentLength = body_bytes.Length
        stream = req.GetRequestStream()
        stream.Write(body_bytes, 0, body_bytes.Length)
        stream.Close()
    else:
        req.ContentLength = 0

    try:
        resp = req.GetResponse()
    except WebException as ex:
        err_body = ""
        if ex.Response:
            err_body = StreamReader(ex.Response.GetResponseStream()).ReadToEnd()
        raise Exception("GitHub API error: {}".format(err_body))

    raw = StreamReader(resp.GetResponseStream()).ReadToEnd()
    resp.Close()
    return json.loads(raw)


def get_file_list(owner, repo, branch):
    """Get recursive file tree from GitHub."""
    ref_data = api_request("GET", "repos/{}/{}/git/ref/heads/{}".format(owner, repo, branch))
    head_sha = ref_data["object"]["sha"]

    commit_data = api_request("GET", "repos/{}/{}/git/commits/{}".format(owner, repo, head_sha))
    tree_sha = commit_data["tree"]["sha"]

    tree_data = api_request("GET", "repos/{}/{}/git/trees/{}?recursive=1".format(owner, repo, tree_sha))
    file_items = [item for item in tree_data.get("tree", []) if item.get("type") == "blob"]
    return file_items, head_sha


def download_blob(owner, repo, blob_sha):
    """Download and decode a single blob from GitHub."""
    data = api_request("GET", "repos/{}/{}/git/blobs/{}".format(owner, repo, blob_sha))
    content = data.get("content", "").replace("\n", "")
    if data.get("encoding", "base64") == "base64":
        return base64.b64decode(content)
    return content.encode("utf-8")


def main():
    output = script.get_output()
    output.close_others()
    output.set_width(600)

    repo_path = get_extension_root()

    output.print_md('## FGD_API Extension Updater')
    output.print_md('**Extension path:** `{}`'.format(repo_path))
    output.print_md('---')

    confirm = forms.alert(
        'This will update the FGD_API extension from GitHub.\n\n'
        'Process:\n'
        '1. Create a backup (zip)\n'
        '2. Preserve Sandbox.panel and lib/\n'
        '3. Download latest files from GitHub\n'
        '4. Restore protected folders\n'
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
        # Step 1: Backup
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

        # Step 2: Preserve protected folders
        output.print_md('### Preserving protected folders...')
        preserved = preserve_folders(repo_path, temp_dir)
        if preserved:
            for name in preserved:
                output.print_md('  [OK] Preserved: {}'.format(name))
        else:
            output.print_md('  [INFO] No protected folders found (Sandbox.panel / lib/)')

        # Step 3: Fetch file list from GitHub
        output.print_md('### Fetching file list from GitHub...')
        try:
            file_items, commit_sha = get_file_list(REPO_OWNER, REPO_NAME, BRANCH)
            output.print_md('  [OK] Found **{}** files (commit `{}`)'.format(len(file_items), commit_sha[:7]))
        except Exception as e:
            output.print_md('  [FAIL] Could not fetch file list:')
            output.print_md('```\n{}\n```'.format(str(e)))
            raise RuntimeError('Failed to fetch file list from GitHub')

        # Step 4: Download and write files
        output.print_md('### Downloading and writing files...')
        success_count = 0
        failed_files = []

        for i, item in enumerate(file_items):
            rel_path = item["path"]
            blob_sha = item["sha"]
            abs_path = os.path.join(repo_path, rel_path.replace("/", "\\"))
            abs_dir = os.path.dirname(abs_path)

            try:
                if not os.path.isdir(abs_dir):
                    os.makedirs(abs_dir)
                raw_bytes = download_blob(REPO_OWNER, REPO_NAME, blob_sha)
                with open(abs_path, "wb") as f:
                    f.write(raw_bytes)
                success_count += 1
            except Exception as e:
                failed_files.append((rel_path, str(e)))

            output.update_progress(i + 1, len(file_items))

        if failed_files:
            output.print_md('  [WARN] {} / {} files written — {} failed'.format(
                success_count, len(file_items), len(failed_files)))
            for path, err in failed_files:
                output.print_md('    - `{}` — {}'.format(path, err))
        else:
            output.print_md('  [OK] All {} files written.'.format(success_count))

        # Step 5: Restore protected folders
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

        # Summary
        output.print_md('---')
        output.print_md('### Update Complete')
        if backup_path:
            output.print_md('Backup saved at: `{}`'.format(backup_path))

        output.print_md('Reloading pyRevit...')
        sessionmgr.reload_pyrevit()

    except RuntimeError:
        if preserved:
            output.print_md('### Restoring protected folders after failure...')
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
            output.print_md('### Restoring protected folders after error...')
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
