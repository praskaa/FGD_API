# -*- coding: utf-8 -*-
"""ExternalEvent-wrapped Revit-API-touching actions.

The Toolbar Manager window is modeless (.Show(), not .ShowDialog()), so its
button-click handlers run OUTSIDE Revit's normal command-execution context —
same rule as Transactions (see pyrevit-wpf skill, section 6). reload_pyrevit()
rebuilds the ribbon at a fairly low level and is NOT safe to call directly
from a WPF Click handler; doing so was the direct cause of the "unrecoverable
error" crash. Route it through ExternalEvent instead, exactly like a
Transaction would be.
"""
from __future__ import unicode_literals

from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent


class _ReloadHandler(IExternalEventHandler):
    def __init__(self, on_done=None):
        self.on_done = on_done   # optional callback, called after reload completes

    def Execute(self, uiapp):
        try:
            from pyrevit.loader import sessionmgr
            sessionmgr.reload_pyrevit()
        finally:
            if self.on_done is not None:
                try:
                    self.on_done()
                except Exception:
                    pass

    def GetName(self):
        return u'Toolbar Manager Reload Handler'


_handlers = {}
_events   = {}


def init_events(on_reload_done=None):
    """Call once from BrowserWindow.__init__, while still inside the Revit
    API context of the button click that opened the window."""
    h = _ReloadHandler(on_done=on_reload_done)
    _handlers['reload'] = h
    _events['reload']   = ExternalEvent.Create(h)


def request_reload():
    """Called from ui.py (WPF thread). Queues the reload on Revit's next
    idle tick — does not block and does not run reload_pyrevit() itself."""
    _events['reload'].Raise()
