# -*- coding: utf-8 -*-
title = "Toolbar\nManager"
doc = """Version = 0.1
Date    = 15.08.2026

Description:
Reorder, rename, move, and delete existing pyRevit panels/buttons/
stacks/pulldowns within this extension, without touching folders by hand.

How-To:
1. Click to open the manager window (stays open while you work in Revit).
2. Select an item in the tree on the left.
3. Rename / reorder / move to another panel or tab / delete from the panel on the right.
4. Click "Reload pyRevit" when done to see changes on the ribbon.

To-Do:
[FEATURE] - Maintain and extend as needed.

Last Updates:
- [15.08.2026] v0.1 Initial version: scan, reorder, rename, move, delete.

Author: PrasKaa"""

__persistentengine__ = True

import os
import sys
import os
import socket
import clr

clr.AddReference('System.Net.Http')
from System.Net.Http import HttpClient, StringContent
from System.Text import Encoding

# --- Telemetry config ---
_SB_URL = "https://mcpqeksbbsmchxlishej.supabase.co/rest/v1/telemetry"
_SB_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1jcHFla3NiYnNtY2h4bGlzaGVqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk4MDUxMDMsImV4cCI6MjEwNTM4MTEwM30.xEWidsKw5MUZ8j19RxTg2sFP7MCPYOyebbWIp9f2a3Y"


def _send_telemetry(script_name):
    try:
        payload = (
            '{"script_name":"%s","user_name":"%s","machine_name":"%s","revit_version":"%s"}'
            % (script_name, os.environ.get("USERNAME", ""),
               socket.gethostname(), __revit__.Application.VersionNumber)
        )
        client = HttpClient()
        client.DefaultRequestHeaders.Add("apikey", _SB_KEY)
        client.DefaultRequestHeaders.Add("Authorization", "Bearer " + _SB_KEY)
        content = StringContent(payload, Encoding.UTF8, "application/json")
        client.PostAsync(_SB_URL, content)
    except:
        pass
_send_telemetry('FGD-Toolbar Manager')   # send telemetry to Supabase
_window = globals().get('_window', None)

if _window is not None and _window.IsLoaded:
    _window.Focus()
    _window.Activate()
else:
    # Purge module cache so source edits are picked up without restarting
    # Revit (mandatory with a persistent engine — see pyrevit-wpf skill).
    _local_modules = ['ui', 'core', 'settings', 'view_actions']
    for _m in _local_modules:
        if _m in sys.modules:
            del sys.modules[_m]

    def _find_extension_root(start_path):
        """Walk up from this script until a *.extension folder is found."""
        path = start_path
        while path and path != os.path.dirname(path):
            if path.endswith('.extension'):
                return path
            path = os.path.dirname(path)
        return None

    path_pushbutton = os.path.dirname(os.path.abspath(__file__))
    path_extension  = _find_extension_root(path_pushbutton)

    if path_extension is None:
        from pyrevit import forms
        forms.alert(
            'Could not locate the parent .extension folder for this tool.',
            exitscript=True)

    from ui import BrowserWindow
    _window = BrowserWindow(path_extension)
    _window.Show()
