# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import os
import json

THIS_DIR    = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(THIS_DIR, '_settings.json')

_DEFAULTS = {'dark_mode': False, 'always_on_top': False}


def load_settings():
    if not os.path.exists(SETTINGS_PATH):
        return dict(_DEFAULTS)
    try:
        with open(SETTINGS_PATH, 'rb') as f:
            data = json.loads(f.read().decode('utf-8'))
        merged = dict(_DEFAULTS)
        merged.update(data)
        return merged
    except Exception:
        return dict(_DEFAULTS)


def save_settings(data):
    merged = load_settings()
    merged.update(data)
    try:
        with open(SETTINGS_PATH, 'wb') as f:
            f.write(json.dumps(merged).encode('utf-8'))
    except Exception:
        pass
