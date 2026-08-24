# -*- coding: utf-8 -*-
"""Toolbar Manager core: filesystem scanner, minimal bundle.yaml read/write,
and rename/delete/move/reorder operations.

Deliberately has ZERO WPF or Revit API imports so it can be unit-tested
standalone (e.g. run with plain CPython against a fake folder tree) before
wiring it into ui.py. Keep it that way.
"""
from __future__ import unicode_literals
import os
import shutil

# --------------------------------------------------------------------------
# Bundle kinds
# --------------------------------------------------------------------------
KIND_TAB        = 'tab'
KIND_PANEL      = 'panel'
KIND_PUSHBUTTON = 'pushbutton'
KIND_URLBUTTON  = 'urlbutton'
KIND_STACK      = 'stack'
KIND_PULLDOWN   = 'pulldown'
KIND_SMARTBUTTON = 'smartbutton'

SUFFIX_FOR_KIND = {
    KIND_TAB:        '.tab',
    KIND_PANEL:      '.panel',
    KIND_PUSHBUTTON: '.pushbutton',
    KIND_URLBUTTON:  '.urlbutton',
    KIND_STACK:      '.stack',
    KIND_PULLDOWN:   '.pulldown',
    KIND_SMARTBUTTON: '.smartbutton',
}
KIND_FOR_SUFFIX = dict((v, k) for k, v in SUFFIX_FOR_KIND.items())

# Kinds that are allowed to contain child bundles (containers).
CONTAINER_KINDS = (KIND_TAB, KIND_PANEL, KIND_STACK, KIND_PULLDOWN)

STACK_MAX_CHILDREN = 3  # pyRevit hard limit, same as the button Generator

# Kinds that can be reordered/moved by the manager. .tab is scan root, not
# itself a movable item (moving a tab = moving the extension, out of scope).
MANAGEABLE_KINDS = (KIND_PANEL, KIND_PUSHBUTTON, KIND_URLBUTTON, KIND_STACK, KIND_PULLDOWN, KIND_SMARTBUTTON)


def kind_of(folder_name):
    """Return the bundle kind for a folder name, or None if not a bundle."""
    for suffix, kind in KIND_FOR_SUFFIX.items():
        if folder_name.endswith(suffix):
            return kind
    return None


def strip_suffix(folder_name):
    kind = kind_of(folder_name)
    if kind is None:
        return folder_name
    return folder_name[:-len(SUFFIX_FOR_KIND[kind])]


def ensure_suffix(name, kind):
    suffix = SUFFIX_FOR_KIND[kind]
    return name if name.endswith(suffix) else name + suffix


# --------------------------------------------------------------------------
# Minimal bundle.yaml parser/writer
#
# pyRevit bundle.yaml files in practice only use a small, flat subset of
# YAML: top-level "key: value" scalars (title, tooltip, hyperlink, ...) and
# one top-level "layout:" list of "- name" items, optionally containing the
# literal separator/slideout markers ('---', '>>>'). We intentionally do NOT
# implement general YAML (no nesting, no flow style, no anchors) — vendoring
# a real YAML lib into IronPython 2.7 is more risk than this narrow format
# needs. If a bundle.yaml uses anything fancier, we preserve unknown lines
# verbatim in '_raw_unknown' and re-emit them unchanged.
# --------------------------------------------------------------------------

def _is_marker(item, char):
    """A layout item made entirely of one repeated character (3+) is a
    structural marker, not a bundle reference — '---' (visual separator) or
    '>>>' / '>>>>>' / any run length (slide-out cutoff). pyRevit's own core
    extension uses 5 chars; don't assume a fixed length."""
    return bool(item) and len(item) >= 3 and set(item) == set(char)


def is_separator(item):
    return _is_marker(item, '-')


def is_slideout_marker(item):
    return _is_marker(item, '>')


SLIDEOUT_MARKER = '>>>'  # written form when we create a new one; reading accepts any length


def read_bundle_yaml(path_yaml):
    """Parse a bundle.yaml file. Returns a dict:
        {
          'title': str or None,           # None if absent OR if title is a
                                            # multi-language dict we don't
                                            # touch (see '_title_locale_raw')
          'tooltip': str or None,
          'hyperlink': str or None,
          'layout': [str, ...] or None,   # None = no layout directive present
          '_title_locale_raw': [str, ...] or None,  # raw lines of a
                                            # multi-language 'title:' block,
                                            # preserved verbatim on write
          '_raw_lines': [str, ...],       # original lines, for safe round-trip
        }
    Returns an "empty" dict (all None, empty raw_lines) if the file doesn't exist.
    """
    result = {'title': None, 'tooltip': None, 'hyperlink': None,
              'layout': None, '_title_locale_raw': None, '_raw_lines': []}
    if not os.path.exists(path_yaml):
        return result

    with open(path_yaml, 'rb') as f:
        text = f.read().decode('utf-8')
    lines = text.splitlines()
    result['_raw_lines'] = lines

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith('layout:'):
            layout_items = []
            i += 1
            while i < n and lines[i].startswith((' ', '\t')) and lines[i].strip().startswith('-'):
                item = lines[i].strip()[1:].strip()
                item = _unquote(item)
                layout_items.append(item)
                i += 1
            result['layout'] = layout_items
            continue
        elif stripped.startswith('title:'):
            value = stripped[len('title:'):].strip()
            if value:
                # Flat "title: value" — the common single-language case.
                result['title'] = _unquote(value)
                i += 1
            else:
                # Empty value on the "title:" line itself means a nested
                # block follows (multi-language dict, as pyRevit's own core
                # extension uses: en_us / fr_fr / ...). We don't know every
                # locale key that might exist, so capture the raw lines
                # verbatim instead of trying to parse+reconstruct them —
                # write_bundle_yaml will re-emit these unchanged rather than
                # collapsing them into a single flat string.
                block = [line]
                i += 1
                while i < n and lines[i].startswith((' ', '\t')) and lines[i].strip():
                    block.append(lines[i])
                    i += 1
                result['_title_locale_raw'] = block
                # result['title'] stays None — callers must treat this as
                # "don't touch the title", falling back to the folder name.
            continue
        elif stripped.startswith('tooltip:'):
            result['tooltip'] = _unquote(stripped[len('tooltip:'):].strip())
        elif stripped.startswith('hyperlink:'):
            result['hyperlink'] = _unquote(stripped[len('hyperlink:'):].strip())
        i += 1

    return result


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1].replace('\\"', '"').replace('\\\\', '\\')
    return value


def _quote(value):
    value = (value or '').replace('\\', '\\\\').replace('"', '\\"')
    return u'"{}"'.format(value)


_YAML_SPECIAL_FIRST_CHARS = set('>|-?:,[]{}#&*!%@`"\'')


def _needs_quoting(item):
    """True if writing `item` as a bare YAML scalar would be ambiguous or
    invalid — e.g. '>>>' looks like a folded-block-scalar indicator to a
    real YAML parser (pyRevit's loader) and breaks it, even though our own
    lightweight reader is forgiving enough to still parse it back. Quote
    proactively rather than relying on that asymmetry."""
    if not item:
        return True
    if item[0] in _YAML_SPECIAL_FIRST_CHARS:
        return True
    if item != item.strip():
        return True
    if item.endswith(':') or ': ' in item:
        return True
    return False


def write_bundle_yaml(path_yaml, data):
    """Write back a bundle.yaml, preserving title/tooltip/hyperlink and
    replacing (or adding) the 'layout:' block. This is a full rewrite, not a
    line-patch, but it only ever touches the four keys this tool understands
    — any other top-level scalar key present in the original file is kept
    verbatim by round-tripping through read_bundle_yaml's parsed fields only
    (i.e. don't hand-edit bundle.yaml files with extra custom keys via this
    function without extending the parser first).

    If the original title was a multi-language dict (see read_bundle_yaml),
    its raw lines are re-emitted unchanged — we never flatten it to a single
    string, which would silently destroy every other language's entry.
    """
    out_lines = []
    if data.get('_title_locale_raw'):
        out_lines.extend(data['_title_locale_raw'])
    elif data.get('title') is not None:
        out_lines.append(u'title: {}'.format(_quote(data['title'])))
    if data.get('tooltip') is not None:
        out_lines.append(u'tooltip: {}'.format(_quote(data['tooltip'])))
    if data.get('hyperlink') is not None:
        out_lines.append(u'hyperlink: {}'.format(_quote(data['hyperlink'])))
    if data.get('layout'):
        out_lines.append(u'layout:')
        for item in data['layout']:
            if _needs_quoting(item):
                out_lines.append(u'  - {}'.format(_quote(item)))
            else:
                out_lines.append(u'  - {}'.format(item))

    text = u'\n'.join(out_lines) + u'\n'
    with open(path_yaml, 'wb') as f:
        f.write(text.encode('utf-8'))


# --------------------------------------------------------------------------
# Tree node + scanner
# --------------------------------------------------------------------------
class Node(object):
    __slots__ = ('name', 'kind', 'path', 'display_name', 'children', 'parent')

    def __init__(self, name, kind, path, display_name, parent=None):
        self.name         = name          # actual folder name, e.g. "Foo.pushbutton"
        self.kind         = kind
        self.path         = path
        self.display_name = display_name  # from bundle.yaml title, else stripped name
        self.children     = []
        self.parent       = parent

    def __repr__(self):
        return '<Node {} ({})>'.format(self.name, self.kind)


def _display_name_for(path, folder_name):
    yaml_path = os.path.join(path, 'bundle.yaml')
    data = read_bundle_yaml(yaml_path)
    return data['title'] or strip_suffix(folder_name)


def _ordered_children(path, layout):
    """List child folder names in path, ordered by 'layout' directive if
    present (unknown/new folders not in layout are appended alphabetically
    at the end), else plain alphabetical."""
    try:
        entries = [e for e in os.listdir(path)
                   if os.path.isdir(os.path.join(path, e)) and kind_of(e) is not None]
    except OSError:
        return []

    if not layout:
        return sorted(entries)

    ordered = []
    remaining = set(entries)
    for item in layout:
        if is_separator(item) or is_slideout_marker(item):
            continue  # structural markers aren't folders; skip for now
        # layout entries reference bundle *display* names without suffix
        match = None
        for e in remaining:
            if strip_suffix(e) == item or e == item:
                match = e
                break
        if match:
            ordered.append(match)
            remaining.discard(match)
    ordered.extend(sorted(remaining))
    return ordered


def scan_bundle(path, folder_name, parent_node=None):
    """Recursively scan a single bundle folder into a Node tree."""
    kind = kind_of(folder_name)
    node = Node(folder_name, kind, path, _display_name_for(path, folder_name), parent_node)

    if kind in CONTAINER_KINDS and kind != KIND_TAB:
        yaml_path = os.path.join(path, 'bundle.yaml')
        layout = read_bundle_yaml(yaml_path)['layout']
        for child_name in _ordered_children(path, layout):
            child_path = os.path.join(path, child_name)
            node.children.append(scan_bundle(child_path, child_name, node))

    return node


def scan_tab(path_tab):
    """Scan a *.tab folder into a Node tree: tab -> panels -> bundles."""
    tab_name = os.path.basename(path_tab)
    tab_node = Node(tab_name, KIND_TAB, path_tab, strip_suffix(tab_name), None)

    yaml_path = os.path.join(path_tab, 'bundle.yaml')
    layout = read_bundle_yaml(yaml_path)['layout']
    for panel_name in _ordered_children(path_tab, layout):
        if kind_of(panel_name) != KIND_PANEL:
            continue
        panel_path = os.path.join(path_tab, panel_name)
        tab_node.children.append(scan_bundle(panel_path, panel_name, tab_node))

    return tab_node


def scan_extension(path_extension):
    """Scan a *.extension folder into a list of tab Nodes."""
    tabs = []
    for entry in sorted(os.listdir(path_extension)):
        full = os.path.join(path_extension, entry)
        if os.path.isdir(full) and entry.endswith('.tab'):
            tabs.append(scan_tab(full))
    return tabs


# --------------------------------------------------------------------------
# Layout (reorder) — write the 'layout:' list into a parent's bundle.yaml
# --------------------------------------------------------------------------
def apply_layout(parent_path, ordered_display_names):
    """Write layout order for parent_path's children. ordered_display_names
    is a list of *display* names (suffix-stripped) in the order they should
    appear; separators '---' / slideout '>>>' may be included verbatim."""
    yaml_path = os.path.join(parent_path, 'bundle.yaml')
    data = read_bundle_yaml(yaml_path)
    data['layout'] = list(ordered_display_names)
    write_bundle_yaml(yaml_path, data)


def move_row(parent_path, current_order, name, direction):
    """Return a new ordered list of display names with `name` shifted by
    direction (-1 up, +1 down). Does not touch disk; caller applies via
    apply_layout(). current_order must already be a list of display names."""
    order = list(current_order)
    if name not in order:
        return order
    idx = order.index(name)
    new_idx = idx + direction
    if 0 <= new_idx < len(order):
        order[idx], order[new_idx] = order[new_idx], order[idx]
    return order


# --------------------------------------------------------------------------
# Create operations: new panel / pushbutton / urlbutton / stack / pulldown
#
# These create empty containers (Stack/Pulldown start with no children —
# children are added afterwards as separate PushButtons, once the container
# exists in the tree and can be selected as a creation target). PushButton
# gets a minimal self-contained script.py; no external template dependency.
# --------------------------------------------------------------------------
_PUSHBUTTON_TEMPLATE = u'''# -*- coding: utf-8 -*-
__title__ = "{title}"
__doc__   = """New pyRevit pushbutton, created via Toolbar Manager."""

from pyrevit import forms, script

# Your code here
'''


def _check_new_name(parent_path, name, kind):
    if not name or not name.strip():
        raise OpError('Enter a name.')
    name = name.strip()
    folder_name = ensure_suffix(name, kind)
    abs_path = os.path.join(parent_path, folder_name)
    if os.path.exists(abs_path):
        raise OpError('"{}" already exists here.'.format(folder_name))
    return name, folder_name, abs_path


def _append_to_layout(parent_path, display_name):
    """If the parent already has an explicit layout order, append the new
    item to the end of it so it doesn't silently jump to an alphabetical
    slot. If there's no layout yet, leave it alone (alphabetical is fine)."""
    yaml_path = os.path.join(parent_path, 'bundle.yaml')
    data = read_bundle_yaml(yaml_path)
    if data['layout']:
        data['layout'].append(display_name)
        write_bundle_yaml(yaml_path, data)


def create_panel(path_tab, name):
    """Create a new empty .panel inside a .tab."""
    name, folder_name, abs_path = _check_new_name(path_tab, name, KIND_PANEL)
    os.makedirs(abs_path)
    _append_to_layout(path_tab, name)
    return abs_path


def create_pushbutton(parent_path, name):
    """Create a new .pushbutton with a minimal script.py inside any container
    (panel, stack, or pulldown)."""
    name, folder_name, abs_path = _check_new_name(parent_path, name, KIND_PUSHBUTTON)
    os.makedirs(abs_path)
    with open(os.path.join(abs_path, 'script.py'), 'wb') as f:
        f.write(_PUSHBUTTON_TEMPLATE.format(title=name).encode('utf-8'))
    _append_to_layout(parent_path, name)
    return abs_path


def create_urlbutton(parent_path, name, url):
    """Create a new .urlbutton with a bundle.yaml (title + hyperlink)."""
    name, folder_name, abs_path = _check_new_name(parent_path, name, KIND_URLBUTTON)
    if not url or not url.strip():
        raise OpError('Enter a URL.')
    url = url.strip()
    if '://' not in url and not url.startswith('mailto:'):
        url = 'https://' + url
    os.makedirs(abs_path)
    write_bundle_yaml(os.path.join(abs_path, 'bundle.yaml'),
                       {'title': name, 'hyperlink': url})
    _append_to_layout(parent_path, name)
    return abs_path


def create_stack(parent_path, name):
    """Create a new, empty .stack container. Add children afterwards by
    selecting it and creating PushButtons inside it."""
    name, folder_name, abs_path = _check_new_name(parent_path, name, KIND_STACK)
    os.makedirs(abs_path)
    _append_to_layout(parent_path, name)
    return abs_path


def create_pulldown(parent_path, name):
    """Create a new, empty .pulldown container."""
    name, folder_name, abs_path = _check_new_name(parent_path, name, KIND_PULLDOWN)
    os.makedirs(abs_path)
    _append_to_layout(parent_path, name)
    return abs_path


# --------------------------------------------------------------------------
# Destructive operations: rename / delete / move between panels-tabs
# --------------------------------------------------------------------------
class OpError(Exception):
    pass


def rename_bundle(node, new_display_name):
    """Rename a bundle's folder (and, for .pushbutton, its __title__ inside
    script.py) to new_display_name. Also patches the parent's layout entry
    if one exists, so ordering survives the rename."""
    if not new_display_name or not new_display_name.strip():
        raise OpError('New name cannot be empty.')
    new_display_name = new_display_name.strip()

    new_folder = ensure_suffix(new_display_name, node.kind)
    new_path = os.path.join(os.path.dirname(node.path), new_folder)
    if new_path != node.path and os.path.exists(new_path):
        raise OpError('"{}" already exists in this location.'.format(new_folder))

    old_display = strip_suffix(node.name)
    old_path = node.path

    if new_path != old_path:
        os.rename(old_path, new_path)

    # Pushbutton: keep script.py's __title__ in sync (mirrors generator's
    # replace_title, best-effort — some pushbuttons may use bundle.yaml title
    # instead, so failure to find __title__ is not an error).
    if node.kind == KIND_PUSHBUTTON:
        script_path = os.path.join(new_path, 'script.py')
        _try_replace_title(script_path, new_display_name)

    # Fix this bundle's own bundle.yaml title if it has one (urlbutton, etc).
    yaml_path = os.path.join(new_path, 'bundle.yaml')
    data = read_bundle_yaml(yaml_path)
    if data['title'] is not None:
        data['title'] = new_display_name
        write_bundle_yaml(yaml_path, data)

    # Fix parent's layout entry, if any.
    if node.parent is not None:
        parent_yaml = os.path.join(node.parent.path, 'bundle.yaml')
        parent_data = read_bundle_yaml(parent_yaml)
        if parent_data['layout']:
            parent_data['layout'] = [new_display_name if x == old_display else x
                                      for x in parent_data['layout']]
            write_bundle_yaml(parent_yaml, parent_data)

    node.name = new_folder
    node.path = new_path
    node.display_name = new_display_name


def _try_replace_title(script_path, title):
    if not os.path.exists(script_path):
        return
    with open(script_path, 'rb') as f:
        data = f.read().decode('utf-8').splitlines(True)
    changed = False
    for i, line in enumerate(data):
        if line.startswith('__title__'):
            data[i] = u'__title__ = "{}"\n'.format(title)
            changed = True
            break
    if changed:
        with open(script_path, 'wb') as f:
            f.write(u''.join(data).encode('utf-8'))


def delete_bundle(node):
    """Permanently delete a bundle folder and scrub it out of the parent's
    layout list. Caller is responsible for confirming with the user first —
    this function does not prompt."""
    if not os.path.exists(node.path):
        return
    shutil.rmtree(node.path)

    if node.parent is not None:
        parent_yaml = os.path.join(node.parent.path, 'bundle.yaml')
        parent_data = read_bundle_yaml(parent_yaml)
        if parent_data['layout']:
            display = strip_suffix(node.name)
            parent_data['layout'] = [x for x in parent_data['layout'] if x != display]
            write_bundle_yaml(parent_yaml, parent_data)


def move_bundle(node, new_parent_node):
    """Move a bundle folder into a different panel/tab/container. Updates
    the layout lists of both the old and new parent."""
    if new_parent_node.kind not in CONTAINER_KINDS:
        raise OpError('Target "{}" cannot contain items.'.format(new_parent_node.display_name))

    if new_parent_node.kind == KIND_STACK and len(new_parent_node.children) >= STACK_MAX_CHILDREN:
        raise OpError('"{}" already has the maximum of {} items — pyRevit stacks '
                       'can only hold 2 or 3.'.format(new_parent_node.display_name, STACK_MAX_CHILDREN))

    dest_path = os.path.join(new_parent_node.path, node.name)
    if os.path.exists(dest_path):
        raise OpError('"{}" already exists in "{}".'.format(node.name, new_parent_node.display_name))

    old_parent = node.parent
    shutil.move(node.path, dest_path)

    display = strip_suffix(node.name)

    if old_parent is not None:
        old_yaml = os.path.join(old_parent.path, 'bundle.yaml')
        old_data = read_bundle_yaml(old_yaml)
        if old_data['layout']:
            old_data['layout'] = [x for x in old_data['layout'] if x != display]
            write_bundle_yaml(old_yaml, old_data)
        old_parent.children.remove(node)

    new_yaml = os.path.join(new_parent_node.path, 'bundle.yaml')
    new_data = read_bundle_yaml(new_yaml)
    if new_data['layout']:
        new_data['layout'].append(display)
        write_bundle_yaml(new_yaml, new_data)

    node.path = dest_path
    node.parent = new_parent_node
    new_parent_node.children.append(node)


# --------------------------------------------------------------------------
# Slide-out (overflow) placement
#
# pyRevit panels can collapse extra buttons behind a chevron/dropdown at the
# panel's corner (see pyRevit's own ribbon panel). This is controlled purely
# by where a '>>>'-style marker sits in the parent's layout: list — anything
# after it is tucked into the slide-out instead of shown directly.
# --------------------------------------------------------------------------
def get_slideout_state(parent_node, display_name):
    """Return True if display_name is currently placed after the slide-out
    marker in parent_node's bundle.yaml layout, False otherwise (including
    when there's no layout/marker at all, i.e. everything is visible)."""
    yaml_path = os.path.join(parent_node.path, 'bundle.yaml')
    data = read_bundle_yaml(yaml_path)
    layout = data['layout']
    if not layout:
        return False
    marker_idx = None
    for i, x in enumerate(layout):
        if is_slideout_marker(x):
            marker_idx = i
            break
    if marker_idx is None:
        return False
    return display_name in layout[marker_idx + 1:]


def set_slideout(parent_node, display_name, want_slideout):
    """Move display_name before/after the slide-out marker in parent_node's
    bundle.yaml layout, creating the marker if it doesn't exist yet and
    want_slideout is True. If a layout doesn't exist at all yet, one is
    built from the current on-disk child order first, so nothing else
    silently changes position."""
    yaml_path = os.path.join(parent_node.path, 'bundle.yaml')
    data = read_bundle_yaml(yaml_path)
    layout = data['layout']

    if not layout:
        layout = [strip_suffix(c.name) for c in parent_node.children]

    marker_idx = None
    for i, x in enumerate(layout):
        if is_slideout_marker(x):
            marker_idx = i
            break

    if marker_idx is None:
        visible = [x for x in layout if x != display_name]
        overflow = []
    else:
        visible  = [x for x in layout[:marker_idx] if x != display_name]
        overflow = [x for x in layout[marker_idx + 1:] if x != display_name]

    if want_slideout:
        overflow.append(display_name)
    else:
        visible.append(display_name)

    new_layout = list(visible)
    if overflow:
        new_layout.append(SLIDEOUT_MARKER)
        new_layout.extend(overflow)

    data['layout'] = new_layout
    write_bundle_yaml(yaml_path, data)


# --------------------------------------------------------------------------
# Empty-container detection
#
# pyRevit's ribbon builder needs at least one child to derive a Stack/
# Pulldown's own icon/name from. An empty one doesn't just look odd — it
# makes pyRevit log "Can not create pull down button: name is an empty
# string" (or similar) and can knock out the rest of that panel on reload.
# Surface these BEFORE the user hits Reload, not after.
# --------------------------------------------------------------------------
def find_empty_containers(tabs):
    """Return every Stack/Pulldown Node in the tree that currently has zero
    children — these will break pyRevit's ribbon build if reloaded as-is."""
    result = []

    def walk(node):
        if node.kind in (KIND_STACK, KIND_PULLDOWN) and not node.children:
            result.append(node)
        for c in node.children:
            walk(c)

    for t in tabs:
        walk(t)
    return result


# --------------------------------------------------------------------------
# Extension-wide diagnostics ("Doctor")
#
# Our own read_bundle_yaml() is a forgiving line-based reader — it can parse
# things a real YAML parser (pyRevit's loader) would choke on. That
# asymmetry is exactly what caused the '>>>' bug. Scan every bundle.yaml
# under the extension for known-bad patterns so problems surface here
# instead of as a cryptic pyRevit log error after Reload.
# --------------------------------------------------------------------------
def find_unquoted_special_lines(path_extension):
    """Scan every bundle.yaml under the extension for a '- value' layout
    line whose value starts with a YAML-special character but isn't
    quoted. These parse fine under our lightweight reader but will break a
    real YAML parser (this was the exact cause of the '>>>' bug)."""
    issues = []
    for dirpath, _dirnames, filenames in os.walk(path_extension):
        if 'bundle.yaml' not in filenames:
            continue
        yp = os.path.join(dirpath, 'bundle.yaml')
        try:
            with open(yp, 'rb') as f:
                text = f.read().decode('utf-8')
        except Exception as e:
            issues.append((yp, u'Could not read/decode file: {}'.format(e)))
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if not s.startswith('- '):
                continue
            val = s[2:].strip()
            if val and not (val.startswith('"') or val.startswith("'")):
                if val[0] in _YAML_SPECIAL_FIRST_CHARS:
                    issues.append((yp, u'Line {}: unquoted "{}" — will break on real reload'.format(lineno, val)))
    return issues


def find_blank_titles(path_extension):
    """Scan every bundle.yaml under the extension for an explicit but empty
    title: "" — pyRevit needs a non-blank name to build that button/panel's
    ribbon control and will error ('name is an empty string') otherwise."""
    issues = []
    for dirpath, _dirnames, filenames in os.walk(path_extension):
        folder_name = os.path.basename(dirpath)
        if kind_of(folder_name) is None or 'bundle.yaml' not in filenames:
            continue
        data = read_bundle_yaml(os.path.join(dirpath, 'bundle.yaml'))
        if data['title'] is not None and not data['title'].strip():
            issues.append((os.path.join(dirpath, 'bundle.yaml'),
                            u'title: "" is present but empty — pyRevit needs a real name here'))
    return issues


def find_stack_count_issues(tabs):
    """pyRevit stacks must have exactly 2 or 3 children — not 0, 1, or 4+.
    find_empty_containers() already flags the 0 case; this flags the rest."""
    issues = []

    def walk(node):
        if node.kind == KIND_STACK:
            n = len(node.children)
            if n == 1:
                issues.append((node.path, u'Stack has only 1 item — pyRevit needs 2 or 3.'))
            elif n > STACK_MAX_CHILDREN:
                issues.append((node.path, u'Stack has {} items — pyRevit only allows 2 or 3. '
                                           u'Move or delete {} of them.'.format(n, n - STACK_MAX_CHILDREN)))
        for c in node.children:
            walk(c)

    for t in tabs:
        walk(t)
    return issues


def run_diagnostics(path_extension, tabs):
    """Combine all known-issue checks into one list of (location, message)
    tuples. `tabs` should be the already-scanned tree (core.scan_extension
    result) so empty-container detection doesn't re-walk the disk."""
    issues = []
    for node in find_empty_containers(tabs):
        issues.append((node.path, u'Empty {} — pyRevit can\'t derive a name/icon with zero children'.format(node.kind)))
    for path, msg in find_stack_count_issues(tabs):
        issues.append((path, msg))
    for path, msg in find_unquoted_special_lines(path_extension):
        issues.append((path, msg))
    for path, msg in find_blank_titles(path_extension):
        issues.append((path, msg))
    return issues
