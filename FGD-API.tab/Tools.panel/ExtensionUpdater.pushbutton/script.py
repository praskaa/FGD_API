# -*- coding: utf-8 -*-
title = "Extension\nUpdater"
doc = """Version = 1.4
Date    = 31.08.2026

Description:
Update FGD_API extension from GitHub via REST API (no git required).
Deletes all local files except Sandbox.panel, then downloads fresh copy.
lib/ folder is overwritten by the remote version.

How-To:
1. Click to run the updater.
2. Confirm the action.
3. Script will backup, clean, download, restore Sandbox, and reload.

Setup (optional, for higher rate limit):
Create github_config.json (see CONFIG_PATH in script) with:
{"github_token_read": "ghp_xxxxxxxxxxxx"}

Last Updates:
- [31.08.2026] v1.4 Added GitHub token auth support to avoid rate limits.
- [31.08.2026] v1.3 Clean local files before download for fresh state.
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
CONFIG_PATH = r"C:\Users\prasetyok\Documents\Github\github_config.json"


def load_github_token():
    """Load GitHub token from config file (optional but recommended)."""
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
            token = cfg.get("github_token_read", "").strip()
            if token:
                return token
        except Exception:
            pass
    return None


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


def preserve_sandbox(repo_path, temp_dir):
    """Move Sandbox.panel to temp before clean+download. lib/ is NOT preserved
    — it gets overwritten by the remote version."""
    tab_dir = os.path.join(repo_path, 'FGD-API.tab')
    sandbox_path = os.path.join(tab_dir, 'Sandbox.panel')
    if os.path.isdir(sandbox_path):
        dest = os.path.join(temp_dir, 'Sandbox.panel')
        shutil.move(sandbox_path, dest)
        return dest
    return None


def restore_sandbox(repo_path, sandbox_temp, temp_dir):
    """Restore Sandbox.panel from temp, overwriting any downloaded version."""
    if not sandbox_temp:
        return False
    tab_dir = os.path.join(repo_path, 'FGD-API.tab')
    dest = os.path.join(tab_dir, 'Sandbox.panel')
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.move(sandbox_temp, dest)
    return True


def clean_local_files(repo_path):
    """Delete ALL local files/folders except Sandbox.panel and lib/.
    lib/ will be overwritten during download (no need to preserve)."""
    tab_dir = os.path.join(repo_path, 'FGD-API.tab')
    sandbox_name = 'Sandbox.panel'
    for item in os.listdir(repo_path):
        if item == 'lib':
            continue  # lib/ gets overwritten, no need to delete
        if item == '.git':
            continue  # keep .git if exists
        item_path = os.path.join(repo_path, item)
        if os.path.isdir(item_path):
            shutil.rmtree(item_path)
        else:
            os.remove(item_path)
    # Also clean inside FGD-API.tab except Sandbox.panel
    if os.path.isdir(tab_dir):
        for item in os.listdir(tab_dir):
            if item == sandbox_name:
                continue
            item_path = os.path.join(tab_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)


def api_request(method, endpoint, token, body=None):
    """Make a GitHub API request. Token is optional but recommended (higher rate limit)."""
    url = "{}/{}".format(API_BASE, endpoint.lstrip("/"))
    req = HttpWebRequest.Create(url)
    req.Method = method
    req.ContentType = "application/json"
    req.Accept = "application/vnd.github+json"
    if token:
        req.Headers.Add("Authorization", "Bearer {}".format(token))
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


def get_file_list(owner, repo, branch, token):
    """Get recursive file tree from GitHub."""
    ref_data = api_request("GET", "repos/{}/{}/git/ref/heads/{}".format(owner, repo, branch), token)
    head_sha = ref_data["object"]["sha"]

    commit_data = api_request("GET", "repos/{}/{}/git/commits/{}".format(owner, repo, head_sha), token)
    tree_sha = commit_data["tree"]["sha"]

    tree_data = api_request("GET", "repos/{}/{}/git/trees/{}?recursive=1".format(owner, repo, tree_sha), token)
    file_items = [item for item in tree_data.get("tree", []) if item.get("type") == "blob"]
    return file_items, head_sha


def download_blob(owner, repo, blob_sha, token):
    """Download and decode a single blob from GitHub."""
    data = api_request("GET", "repos/{}/{}/git/blobs/{}".format(owner, repo, blob_sha), token)
    content = data.get("content", "").replace("\n", "")
    if data.get("encoding", "base64") == "base64":
        return base64.b64decode(content)
    return content.encode("utf-8")


def main():
    output = script.get_output()
    output.close_others()
    output.set_width(600)

    repo_path = get_extension_root()
    token = load_github_token()

    output.print_md('## FGD_API Extension Updater')
    output.print_md('**Extension path:** `{}`'.format(repo_path))
    if token:
        output.print_md('**Auth:** Token loaded (higher rate limit)')
    else:
        output.print_md('**Auth:** No token (60 req/hr limit). Add `github_token_read` to config for higher limit.')
    output.print_md('---')

    confirm = forms.alert(
        'This will update the FGD_API extension from GitHub.\n\n'
        'Process:\n'
        '1. Create a backup (zip)\n'
        '2. Preserve Sandbox.panel (lib/ will be overwritten)\n'
        '3. Delete all other local files\n'
        '4. Download latest files from GitHub\n'
        '5. Restore Sandbox.panel\n'
        '6. Reload pyRevit\n\n'
        'Continue?',
        title='Extension Updater',
        yes=True,
        no=True
    )
    if not confirm:
        script.exit()

    temp_dir = tempfile.mkdtemp(prefix='fgd_update_')
    backup_path = None
    sandbox_temp = None
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

        # Step 2: Preserve Sandbox.panel only
        output.print_md('### Preserving Sandbox.panel...')
        sandbox_temp = preserve_sandbox(repo_path, temp_dir)
        if sandbox_temp:
            output.print_md('  [OK] Preserved: Sandbox.panel')
        else:
            output.print_md('  [INFO] No Sandbox.panel found — nothing to preserve')

        # Step 3: Clean all local files (except lib/ which gets overwritten)
        output.print_md('### Cleaning local files...')
        clean_local_files(repo_path)
        output.print_md('  [OK] Local files cleaned')

        # Step 4: Fetch file list from GitHub
        output.print_md('### Fetching file list from GitHub...')
        try:
            file_items, commit_sha = get_file_list(REPO_OWNER, REPO_NAME, BRANCH, token)
            output.print_md('  [OK] Found **{}** files (commit `{}`)'.format(len(file_items), commit_sha[:7]))
        except Exception as e:
            error_str = str(e)
            output.print_md('  [FAIL] Could not fetch file list:')
            output.print_md('```\n{}\n```'.format(error_str))
            if 'rate limit' in error_str.lower():
                output.print_md('')
                output.print_md('  **Rate limit exceeded!** Create a GitHub token:')
                output.print_md('  1. Go to https://github.com/settings/tokens')
                output.print_md('  2. Generate a token (no scopes needed for public repos)')
                output.print_md('  3. Save to `{}`:'.format(CONFIG_PATH))
                output.print_md('     ```json\n     {"github_token_read": "ghp_xxxx"}\n     ```')
            raise RuntimeError('Failed to fetch file list from GitHub')

        # Step 5: Download and write files
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
                raw_bytes = download_blob(REPO_OWNER, REPO_NAME, blob_sha, token)
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

        # Step 6: Restore Sandbox.panel
        output.print_md('### Restoring Sandbox.panel...')
        restored = restore_sandbox(repo_path, sandbox_temp, temp_dir)
        if restored:
            output.print_md('  [OK] Restored: Sandbox.panel')
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
        if sandbox_temp:
            output.print_md('### Restoring Sandbox.panel after failure...')
            try:
                restore_sandbox(repo_path, sandbox_temp, temp_dir)
                output.print_md('  [OK] Restored Sandbox.panel.')
            except Exception as e:
                output.print_md('  [ERR] Could not restore: {}'.format(e))
                output.print_md('  Temp folder: `{}`'.format(temp_dir))
        forms.alert(
            'Update failed. Your files are safe — Sandbox.panel has been restored.\n\n'
            'Backup: {}'.format(backup_path or 'N/A'),
            title='Update Failed'
        )
    except Exception as e:
        if sandbox_temp:
            output.print_md('### Restoring Sandbox.panel after error...')
            try:
                restore_sandbox(repo_path, sandbox_temp, temp_dir)
                output.print_md('  [OK] Restored Sandbox.panel.')
            except Exception as re:
                output.print_md('  [ERR] Could not restore: {}'.format(re))
                output.print_md('  Temp folder: `{}`'.format(temp_dir))
        forms.alert(
            'Unexpected error: {}\n\nSandbox.panel restored.'.format(e),
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
