# -*- coding: utf-8 -*-
__title__ = "Toolbar\nManager"
__doc__   = """Version = 0.1
Date    = 15.08.2026
________________________________________________________________
Description:
Reorder, rename, move, and delete existing pyRevit panels/buttons/
stacks/pulldowns within this extension, without touching folders by hand.

________________________________________________________________
How-To:
- Click to open the manager window (stays open while you work in Revit)
- Select an item in the tree on the left
- Rename / reorder / move to another panel or tab / delete from the panel on the right
- Click "Reload pyRevit" when you're done to see changes on the ribbon

________________________________________________________________
Last Updates:
- [15.08.2026] v0.1 - Initial version: scan, reorder, rename, move, delete
________________________________________________________________
Author: (adapted from Erik Frits' pyRevit Buttons Generator)"""

__persistentengine__ = True

import os
import sys

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
