# -*- coding: utf-8 -*-
"""Shared path resolution helpers for the FGD Tools extension."""

import os

EXTENSION_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAB_NAME = u'FGD-API'
TOOLS_PANEL = u'Tools'
SANDBOX_PANEL = u'Sandbox'
SLIDEOUT_MARKER = u'>>>'


def get_extension_root():
    return EXTENSION_ROOT


def get_tab_dir():
    return os.path.join(EXTENSION_ROOT, TAB_NAME + u'.tab')


def get_panel_dir(panel_name):
    return os.path.join(get_tab_dir(), panel_name + u'.panel')


def get_button_dir(panel_name, button_name):
    return os.path.join(get_panel_dir(panel_name), button_name + u'.pushbutton')


def get_bundle_yaml_path(bundle_dir):
    return os.path.join(bundle_dir, u'bundle.yaml')


def sanitize_button_name(raw):
    """PascalCase-safe button id: alphanumerics + underscore only, no leading '_'."""
    cleaned = u''.join(ch for ch in raw if ch.isalnum() or ch == u'_')
    if not cleaned or cleaned.startswith(u'_'):
        raise ValueError(u'Invalid button name: {}'.format(raw))
    return cleaned
