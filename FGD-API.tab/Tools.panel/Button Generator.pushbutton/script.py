# -*- coding: utf-8 -*-
title = "Button\nGenerator"
doc = """Version = 1.0
Date    = 25.08.2026

Description:
Quick pyRevit Button Generator with a friendly UI form. Create
PushButtons, URLButtons, Stacks, Pulldowns, or import an existing
script.py straight into a brand-new PushButton in one go.

How-To:
1. Click to open the form.
2. Create rows for each Button/Container.
3. Set Name, select Type (PushButton, From Script, URLButton, Stack, Pulldown).
4. For "From Script": click Browse and pick an existing script.py.
5. Select Target Panel (optional).
6. Click Create Button. Validation issues show as red inline hints.

To-Do:
[FEATURE] - Generate panels/tabs directly from the form.

Last Updates:
- [25.08.2026] v1.0 Ported from TTW-API into PrasKaaPyKit.

Author: PrasKaa"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
#░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
import os, shutil
from pyrevit.loader import sessionmgr      # To Reload pyRevit
from pyrevit import forms, script


# WPF Imports
import clr
clr.AddReference('PresentationFramework')
clr.AddReference('System')
from System                         import Action, Uri, TimeSpan
from System.IO                      import File
from System.Windows                 import Visibility, Thickness, Duration
from System.Windows.Controls        import ComboBoxItem, Control
from System.Windows.Input           import Key, ModifierKeys, Keyboard
from System.Windows.Markup          import XamlReader
from System.Windows.Media           import SolidColorBrush, Color
from System.Windows.Media.Animation import ColorAnimation, RepeatBehavior, FillBehavior
from System.Windows.Media.Imaging   import BitmapImage
from Microsoft.Win32                import OpenFileDialog     # native "Choose script.py" dialog


# ╔═╗╦ ╦╔╗╔╔═╗╔╦╗╦╔═╗╔╗╔╔═╗
# ╠╣ ║ ║║║║║   ║ ║║ ║║║║╚═╗
# ╚  ╚═╝╝╚╝╚═╝ ╩ ╩╚═╝╝╚╝╚═╝ FUNCTIONS
#░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
TYPE_PUSHBUTTON = 'PushButton'
TYPE_SCRIPT     = 'Script'          # NEW: PushButton built from an existing script.py
TYPE_URLBUTTON  = 'URLButton'
TYPE_STACK      = 'Stack'
TYPE_PULLDOWN   = 'Pulldown'
ITEM_TYPES      = (TYPE_PUSHBUTTON, TYPE_SCRIPT, TYPE_URLBUTTON, TYPE_STACK, TYPE_PULLDOWN)
SUFFIXES        = ('.pushbutton', '.urlbutton', '.stack', '.pulldown')
STACK_MAX_CHILDREN = 3
PULLDOWN_MAX_CHILDREN = 10

# Final bundle suffix for each item type (used to build the on-disk folder name).
# "Script" still produces a plain .pushbutton folder - only its script.py source differs.
SUFFIX_FOR_TYPE = {
    TYPE_PUSHBUTTON: '.pushbutton',
    TYPE_SCRIPT:     '.pushbutton',
    TYPE_URLBUTTON:  '.urlbutton',
    TYPE_STACK:      '.stack',
    TYPE_PULLDOWN:   '.pulldown',
}

# Single buttons get a blue selected badge; containers get a red one.
SELECTED_STYLE = {
    TYPE_PUSHBUTTON: 'BadgeSelectedSingle',
    TYPE_SCRIPT:     'BadgeSelectedSingle',
    TYPE_URLBUTTON:  'BadgeSelectedSingle',
    TYPE_STACK:      'BadgeSelectedContainer',
    TYPE_PULLDOWN:   'BadgeSelectedContainer',
}

# Educational hint-bar texts (Bahasa Indonesia) shown while hovering badges.
DEFAULT_HINT = u'Arahkan kursor ke badge tipe untuk melihat penjelasan singkat.'
HINT_FOR_TYPE = {
    TYPE_PUSHBUTTON: u'PushButton: satu tombol menjalankan satu script. Folder .pushbutton.',
    TYPE_SCRIPT:     u'From Script: membuat tombol dari file script.py yang sudah ada (tanpa menulis kode).',
    TYPE_URLBUTTON:  u'URLButton: tombol yang membuka website. Isi kolom URL.',
    TYPE_STACK:      u'Stack: kumpulan maksimal 3 item berjajar - boleh PushButton, Pulldown, atau campuran.',
    TYPE_PULLDOWN:   u'Pulldown: satu tombol yang membuka daftar berisi hingga 10 PushButton.',
}


def strip_suffix(name):
    """Remove any bundle suffix from a name (for use as title)."""
    for sfx in SUFFIXES:
        if name.endswith(sfx):
            return name[:-len(sfx)]
    return name


def ensure_suffix(name, suffix):
    """Append the proper bundle suffix if missing."""
    return name if name.endswith(suffix) else name + suffix


def normalize_url(url):
    """Ensure the URL has a scheme. pyRevit can't open scheme-less URLs
    (e.g. 'google.com'), so default to https:// when none is present."""
    url = (url or '').strip()
    if url and '://' not in url and not url.startswith('mailto:'):
        url = 'https://' + url
    return url


def yaml_double_quote(value):
    """Return a YAML double-quoted scalar so values containing ':' (or other
    YAML-special characters) don't corrupt bundle.yaml."""
    value = (value or '').replace('\\', '\\\\').replace('"', '\\"')
    return u'"{}"'.format(value)


def replace_title(path_script, title):
    """Replace (or insert) the title line inside a script.py file.

    Handles both the canonical PrasKaaPyKit header (``title = "..."``) and
    the legacy ``__title__ = "..."`` form, so imported scripts keep working.

    IronPython 2.7's io.open ignores encoding='utf-8' and decodes with the
    system code page, which crashes on non-ASCII bytes (UnicodeDecodeError on
    0xE2...). Read/write raw bytes and (de|en)code UTF-8 explicitly so any
    non-ASCII content (box-drawing chars, emoji, accented names, etc.)
    survives the round-trip.

    Imported scripts (via "From Script") may not define a title at all - in
    that case a fresh title line is inserted at the top of the file so the
    ribbon button still shows the intended name.
    """
    title = strip_suffix(title)
    title = title.replace('\\', '\\\\').replace('"', '\\"')   # keep the generated script syntax-valid
    with open(path_script, 'rb') as f:
        data = f.read().decode('utf-8').splitlines(True)

    for n, line in enumerate(data):
        if line.startswith('title =') or line.startswith('__title__'):
            data[n] = u'title = "{}"\n'.format(title)
            break
    else:
        # No title found (e.g. an imported/external script) - insert one.
        insert_at = 0
        if data and data[0].startswith('# -*- coding'):
            insert_at = 1
        data.insert(insert_at, u'title = "{}"\n'.format(title))

    with open(path_script, 'wb') as f:
        f.write(u''.join(data).encode('utf-8'))


def create_pushbutton(parent_folder, name, log):
    """Copy the .pushbutton template into parent_folder and rename the title."""
    folder_name = ensure_suffix(name, '.pushbutton')
    abs_path    = os.path.join(parent_folder, folder_name)

    if os.path.exists(abs_path):
        log.append('[SKIP] "{}" already exists.'.format(folder_name))
        return
    try:
        shutil.copytree(path_template, abs_path)
        replace_title(os.path.join(abs_path, 'script.py'), folder_name)
        log.append('[OK]   PushButton "{}"'.format(folder_name))
    except Exception:
        import traceback
        log.append('[ERR]  Could not create "{}"\n{}'.format(folder_name, traceback.format_exc()))


def create_scriptbutton(parent_folder, name, script_path, log):
    """Copy the .pushbutton template (for icon.png/bundle.yaml) into
    parent_folder, then overwrite its script.py with the user-picked file
    and rename the title to match the row's name."""
    folder_name = ensure_suffix(name, '.pushbutton')
    abs_path    = os.path.join(parent_folder, folder_name)

    if os.path.exists(abs_path):
        log.append('[SKIP] "{}" already exists.'.format(folder_name))
        return
    if not script_path or not os.path.exists(script_path):
        log.append('[ERR]  "{}" -> script.py not found: {}'.format(folder_name, script_path))
        return
    try:
        shutil.copytree(path_template, abs_path)
        dst_script = os.path.join(abs_path, 'script.py')
        os.remove(dst_script)                       # drop the template's placeholder script.py
        shutil.copyfile(script_path, dst_script)     # bring in the user's script.py
        replace_title(dst_script, folder_name)
        log.append('[OK]   Script "{}" <- {}'.format(folder_name, script_path))
    except Exception:
        import traceback
        log.append('[ERR]  Could not create "{}"\n{}'.format(folder_name, traceback.format_exc()))


def create_pulldown(parent_folder, name, child_names, log):
    """Create a .pulldown folder containing N child pushbuttons."""
    folder_name = ensure_suffix(name, '.pulldown')
    abs_path    = os.path.join(parent_folder, folder_name)

    if os.path.exists(abs_path):
        log.append('[SKIP] "{}" already exists.'.format(folder_name))
        return
    try:
        os.makedirs(abs_path)
        # Pulldown needs its own icon.png (the ribbon image for the dropdown).
        template_icon = os.path.join(path_template, 'icon.png')
        if os.path.exists(template_icon):
            shutil.copyfile(template_icon, os.path.join(abs_path, 'icon.png'))
        log.append('[OK]   Pulldown "{}"'.format(folder_name))
        for child in child_names:
            create_pushbutton(abs_path, child, log)
    except Exception:
        import traceback
        log.append('[ERR]  Could not create "{}"\n{}'.format(folder_name, traceback.format_exc()))


def create_stack(parent_folder, name, child_names, log):
    """Create a .stack folder containing 2-3 child pushbuttons."""
    folder_name = ensure_suffix(name, '.stack')
    abs_path    = os.path.join(parent_folder, folder_name)

    if os.path.exists(abs_path):
        log.append('[SKIP] "{}" already exists.'.format(folder_name))
        return
    try:
        os.makedirs(abs_path)
        log.append('[OK]   Stack "{}"'.format(folder_name))
        for child in child_names:
            create_pushbutton(abs_path, child, log)
    except Exception:
        import traceback
        log.append('[ERR]  Could not create "{}"\n{}'.format(folder_name, traceback.format_exc()))


def create_urlbutton(parent_folder, name, url, log):
    """Create a .urlbutton folder with bundle.yaml + icon.png."""
    folder_name = ensure_suffix(name, '.urlbutton')
    abs_path    = os.path.join(parent_folder, folder_name)

    if os.path.exists(abs_path):
        log.append('[SKIP] "{}" already exists.'.format(folder_name))
        return
    try:
        os.makedirs(abs_path)
        title       = strip_suffix(name)
        url         = normalize_url(url)
        bundle_yaml = u'title: {}\nhyperlink: {}\n'.format(
            yaml_double_quote(title), yaml_double_quote(url))
        with open(os.path.join(abs_path, 'bundle.yaml'), 'wb') as f:
            f.write(bundle_yaml.encode('utf-8'))
        template_icon = os.path.join(path_template, 'icon.png')
        if os.path.exists(template_icon):
            shutil.copyfile(template_icon, os.path.join(abs_path, 'icon.png'))
        log.append('[OK]   URLButton "{}" -> {}'.format(folder_name, url))
    except Exception:
        import traceback
        log.append('[ERR]  Could not create "{}"\n{}'.format(folder_name, traceback.format_exc()))


def load_xaml_part(filename):
    """Load a standalone XAML file into a fresh visual element."""
    return XamlReader.Parse(File.ReadAllText(os.path.join(path_xaml_dir, filename)))


# ╔═╗╔═╗╦═╗╔╦╗
# ╠╣ ║ ║╠╦╝║║║
# ╚  ╚═╝╩╚═╩ ╩ WPF FORM
#░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
class GeneratorForm(forms.WPFWindow):
    """Custom WPF form. All styling lives in XAML; Python only wires behavior."""

    def __init__(self, xaml_path, panels_dir, panel_choices, default_panel, icon_path=None):
        forms.WPFWindow.__init__(self, xaml_path)
        self.results           = None
        self.panels_dir        = panels_dir
        self.target_panel_path = None     # set on Create

        self.btn_AddRow.Click             += self.on_add_row
        self.btn_Create.Click             += self.on_create
        self.btn_Cancel.Click             += self.on_cancel
        self.btn_Close.Click              += self.on_cancel
        self.PreviewKeyDown               += self.on_window_keydown
        self.titleBar.MouseLeftButtonDown += self.on_titlebar_drag
        self.cb_Panel.SelectionChanged    += self.on_panel_changed
        self.tb_Hint.Text = DEFAULT_HINT

        # Title-bar icon (if file is present)
        if icon_path and os.path.exists(icon_path):
            self.img_TitleIcon.Source = BitmapImage(Uri(icon_path))

        # Target-panel dropdown
        self._populate_panels(panel_choices, default_panel)

        # Default seed rows
        self._add_row('MyButton', TYPE_PUSHBUTTON)
        self._add_row('MyStack',  TYPE_STACK, ['BTN-A', 'BTN-B'])

    # ---- panel selector --------------------------------------------------
    def _populate_panels(self, choices, default):
        for full_name in choices:
            display = full_name.replace('.panel', '')
            item = ComboBoxItem()
            item.Content = display          # full panel name
            item.Tag     = full_name        # full folder name (with .panel)
            self.cb_Panel.Items.Add(item)
            if full_name == default:
                self.cb_Panel.SelectedItem = item
        if self.cb_Panel.SelectedItem is None and self.cb_Panel.Items.Count > 0:
            self.cb_Panel.SelectedIndex = 0

    # ---- custom-chrome handlers ------------------------------------------
    def on_titlebar_drag(self, sender, args):
        self.DragMove()

    # ---- keyboard shortcuts ----------------------------------------------
    def on_window_keydown(self, sender, args):
        if args.Key == Key.Enter and Keyboard.Modifiers == ModifierKeys.Control:
            tb = self._add_row()
            self.Dispatcher.BeginInvoke(Action(lambda: tb.Focus()))
            args.Handled = True

    # ---- row construction -------------------------------------------------
    def _add_row(self, default_name='', default_type=TYPE_PUSHBUTTON, default_children=None):
        default_children = list(default_children or [])

        # Adding a row resolves the "add at least one row" form-level message.
        self._clear_global_error()

        # 1) Load row visual tree
        row = load_xaml_part('RowTemplate.xaml')

        # 2) Find named elements
        tb_name        = row.FindName('tb_Name')
        tb_name_error  = row.FindName('tb_NameError')
        chip_wrap      = row.FindName('chipWrap')
        chip_input_box = row.FindName('chipInputBox')
        tb_chip        = row.FindName('tb_ChipInput')
        url_area       = row.FindName('urlArea')
        tb_url         = row.FindName('tb_Url')
        script_area    = row.FindName('scriptArea')
        btn_browse     = row.FindName('btn_BrowseScript')
        tb_script_path = row.FindName('tb_ScriptPath')
        btn_remove     = row.FindName('btn_Remove')
        badges = {
            TYPE_PUSHBUTTON: (row.FindName('badge_PushButton'), row.FindName('lbl_PushButton')),
            TYPE_SCRIPT:     (row.FindName('badge_Script'),     row.FindName('lbl_Script')),
            TYPE_PULLDOWN:   (row.FindName('badge_Pulldown'),   row.FindName('lbl_Pulldown')),
            TYPE_STACK:      (row.FindName('badge_Stack'),      row.FindName('lbl_Stack')),
            TYPE_URLBUTTON:  (row.FindName('badge_URLButton'),  row.FindName('lbl_URLButton')),
        }

        # 3) Per-row state
        tb_name.Text = default_name
        state = {'kind': default_type, 'children': [], 'chips': {}, 'script_path': None,
                 'tb_name': tb_name, 'tb_url': tb_url,
                 'tb_name_error': tb_name_error}

        # 4) Insert into the tree so DynamicResource styles resolve
        self.sp_Rows.Children.Add(row)

        # 5) Behavior closures
        def at_chip_cap():
            if state['kind'] == TYPE_STACK:
                return len(state['children']) >= STACK_MAX_CHILDREN
            if state['kind'] == TYPE_PULLDOWN:
                return len(state['children']) >= PULLDOWN_MAX_CHILDREN
            return False

        def update_chip_input_visibility():
            chip_input_box.Visibility = Visibility.Collapsed if at_chip_cap() else Visibility.Visible

        def refresh_script_label():
            if state['script_path']:
                tb_script_path.Text = os.path.basename(state['script_path'])
                tb_script_path.ToolTip = state['script_path']
            else:
                tb_script_path.Text = 'No file selected'
                tb_script_path.ToolTip = None

        def browse_script():
            dlg = OpenFileDialog()
            dlg.Title  = 'Select a script.py to import'
            dlg.Filter = 'Python script (*.py)|*.py|All files (*.*)|*.*'
            if state['script_path'] and os.path.exists(state['script_path']):
                dlg.InitialDirectory = os.path.dirname(state['script_path'])
            if dlg.ShowDialog():
                state['script_path'] = dlg.FileName
                self._clear_row_error(state)   # picking a file may fix a "pick a script" error
                # Auto-fill the name field from the script's parent folder / filename,
                # but only if the user hasn't typed a name yet.
                if not (tb_name.Text or '').strip():
                    guess = os.path.basename(os.path.dirname(dlg.FileName))
                    guess = strip_suffix(guess) if guess else os.path.splitext(os.path.basename(dlg.FileName))[0]
                    tb_name.Text = guess
            refresh_script_label()

        def select_type(kind):
            self._clear_row_error(state)    # type change may fix a type-specific issue
            state['kind'] = kind
            for k, (bd, lb) in badges.items():
                if k == kind:
                    bd.Style = bd.FindResource(SELECTED_STYLE[k])
                    lb.Style = lb.FindResource('BadgeTextSelected')
                else:
                    bd.Style = bd.FindResource('BadgeUnselected')
                    lb.Style = lb.FindResource('BadgeTextUnselected')

            if kind == TYPE_URLBUTTON:
                chip_wrap.Visibility   = Visibility.Collapsed
                url_area.Visibility    = Visibility.Visible
                script_area.Visibility = Visibility.Collapsed
            elif kind == TYPE_SCRIPT:
                chip_wrap.Visibility   = Visibility.Collapsed
                url_area.Visibility    = Visibility.Collapsed
                script_area.Visibility = Visibility.Visible
                refresh_script_label()
            elif kind in (TYPE_PULLDOWN, TYPE_STACK):
                chip_wrap.Visibility   = Visibility.Visible
                url_area.Visibility    = Visibility.Collapsed
                script_area.Visibility = Visibility.Collapsed
                update_chip_input_visibility()
            else:   # PushButton -> nothing nested
                chip_wrap.Visibility   = Visibility.Collapsed
                url_area.Visibility    = Visibility.Collapsed
                script_area.Visibility = Visibility.Collapsed

        def remove_chip(text):
            self._clear_row_error(state)    # editing children may fix a count issue
            if text in state['chips']:
                chip_wrap.Children.Remove(state['chips'].pop(text))
            if text in state['children']:
                state['children'].remove(text)
            update_chip_input_visibility()

        def add_chip(text):
            text = (text or '').strip()
            if not text or text in state['children'] or at_chip_cap():
                return False
            chip = load_xaml_part('ChipTemplate.xaml')
            chip.FindName('lbl_Chip').Text = text
            chip.FindName('btn_RemoveChip').Click += lambda s, a: remove_chip(text)
            chip_wrap.Children.Insert(chip_wrap.Children.IndexOf(chip_input_box), chip)
            state['chips'][text] = chip
            state['children'].append(text)
            update_chip_input_visibility()
            return True

        def flush_chip_input():
            if tb_chip.Text:
                add_chip(tb_chip.Text)
                tb_chip.Text = ''
        state['flush'] = flush_chip_input

        def on_chip_text_changed(s, a):
            # Comma in input = commit chip(s); leave any tail after last comma
            if ',' not in tb_chip.Text:
                return
            parts = tb_chip.Text.split(',')
            for piece in parts[:-1]:
                add_chip(piece)
            tb_chip.Text = parts[-1].lstrip()

        def on_chip_keydown(s, a):
            # Ctrl+Enter is handled at Window level; skip
            if a.Key == Key.Enter and Keyboard.Modifiers != ModifierKeys.Control:
                if add_chip(tb_chip.Text):
                    tb_chip.Text = ''
                a.Handled = True
            elif a.Key == Key.Back and not tb_chip.Text and state['children']:
                remove_chip(state['children'][-1])
                a.Handled = True

        # 6) Wire events
        for kind, (bd, _) in badges.items():
            def on_badge_click(s, a, k=kind):
                select_type(k)
                # Auto-focus the relevant input so users don't have to hunt for it
                if k in (TYPE_PULLDOWN, TYPE_STACK) and chip_input_box.Visibility == Visibility.Visible:
                    self.Dispatcher.BeginInvoke(Action(lambda: tb_chip.Focus()))
                elif k == TYPE_URLBUTTON:
                    self.Dispatcher.BeginInvoke(Action(lambda: tb_url.Focus()))
                elif k == TYPE_SCRIPT:
                    self.Dispatcher.BeginInvoke(Action(browse_script))
                a.Handled = True
            bd.MouseLeftButtonDown += on_badge_click
            # Educational hint-bar updates on badge hover.
            bd.MouseEnter += lambda s, a, k=kind: self._set_hint(HINT_FOR_TYPE.get(k, DEFAULT_HINT))
            bd.MouseLeave += lambda s, a: self._set_hint(DEFAULT_HINT)

        tb_chip.TextChanged    += on_chip_text_changed
        tb_chip.PreviewKeyDown += on_chip_keydown
        btn_browse.Click        += lambda s, a: browse_script()
        btn_remove.Click        += lambda s, a: self.sp_Rows.Children.Remove(row)
        # Any edit to this row clears its inline validation message.
        tb_name.TextChanged    += lambda s, a: self._clear_row_error(state)
        tb_url.TextChanged     += lambda s, a: self._clear_row_error(state)
        tb_chip.TextChanged    += lambda s, a: self._clear_row_error(state)

        # 7) Seed defaults
        for c in default_children:
            add_chip(c)
        select_type(default_type)

        row.Tag = state
        return tb_name

    # ---- existing-name conflict feedback ---------------------------------
    def _set_row_error(self, st, message=u'Button Name Already Exists…'):
        """Flash a row's Name field red and show the inline conflict message."""
        tb  = st['tb_name']
        err = st['tb_name_error']
        # A fresh, non-frozen brush: the XAML border binds a shared frozen
        # resource that would throw if animated. Animate this local brush instead.
        brush = SolidColorBrush(Color.FromRgb(0xB4, 0x43, 0x3C))
        tb.BorderBrush     = brush
        tb.BorderThickness = Thickness(1.5)
        if err is not None:
            err.Text       = message
            err.Visibility = Visibility.Visible
        # Short red pulse, then settle on solid red (FillBehavior.Stop).
        anim = ColorAnimation()
        anim.From           = Color.FromRgb(0xF6, 0xDE, 0xDC)   # light red
        anim.To             = Color.FromRgb(0xB4, 0x43, 0x3C)   # solid red
        anim.Duration       = Duration(TimeSpan.FromMilliseconds(160))
        anim.AutoReverse    = True
        anim.RepeatBehavior = RepeatBehavior(2)
        anim.FillBehavior   = FillBehavior.Stop
        brush.BeginAnimation(SolidColorBrush.ColorProperty, anim)

    def _clear_row_error(self, st):
        """Revert a row's Name field to its normal style (no-op if not flagged)."""
        err = st['tb_name_error']
        if err is None or err.Visibility != Visibility.Visible:
            return
        tb = st['tb_name']
        tb.ClearValue(Control.BorderBrushProperty)      # back to the TextBox style
        tb.ClearValue(Control.BorderThicknessProperty)
        err.Visibility = Visibility.Collapsed

    def _clear_all_row_errors(self):
        for row in self.sp_Rows.Children:
            self._clear_row_error(row.Tag)

    def _set_global_error(self, message):
        """Form-level issue with no specific row (e.g. no rows / no panel).
        Shown inline in the footer instead of a pop-up."""
        self.tb_GlobalError.Text       = message
        self.tb_GlobalError.Visibility = Visibility.Visible

    def _clear_global_error(self):
        self.tb_GlobalError.Visibility = Visibility.Collapsed

    def _set_hint(self, text):
        self.tb_Hint.Text = text

    def on_panel_changed(self, sender, args):
        self._clear_global_error()

    # ---- footer event handlers -------------------------------------------
    def on_add_row(self, sender, args):
        tb = self._add_row()
        self.Dispatcher.BeginInvoke(Action(lambda: tb.Focus()))

    def on_cancel(self, sender, args):
        self.results = None
        self.Close()

    def on_create(self, sender, args):
        # Clear all inline messages from the previous attempt — no pop-ups anywhere.
        self._clear_all_row_errors()
        self._clear_global_error()

        rows = list(self.sp_Rows.Children)
        if not rows:
            self._set_global_error('Add at least one row before creating.')
            return

        # Resolve the target panel up front (needed for the existence check).
        selected_panel = self.cb_Panel.SelectedItem
        target_panel   = (os.path.join(self.panels_dir, selected_panel.Tag)
                          if selected_panel is not None else None)

        plan      = []          # validated items, in row order
        seen      = set()       # lowercased folder names -> case-insensitive dedup
        first_bad = None        # first flagged field, to scroll into view
        any_error = False

        # One pass: each problem row gets red text saying exactly what's wrong.
        for row in rows:
            st = row.Tag
            st['flush']()       # commit any unsubmitted child input

            name        = (st['tb_name'].Text or '').strip()
            kind        = st['kind']
            children    = list(st['children'])
            url         = (st['tb_url'].Text or '').strip()
            script_path = st['script_path']

            problem = None
            if not name:
                problem = 'Enter a name for this row.'
            else:
                folder_name = ensure_suffix(name, SUFFIX_FOR_TYPE[kind])
                key = folder_name.lower()   # Windows folder names are case-insensitive
                if key in seen:
                    problem = 'Duplicate name — already used in another row.'
                else:
                    seen.add(key)
                    if kind == TYPE_PULLDOWN and not (1 <= len(children) <= PULLDOWN_MAX_CHILDREN):
                        problem = 'Pulldown needs 1 to {} nested buttons (got {}).'.format(PULLDOWN_MAX_CHILDREN, len(children))
                    elif kind == TYPE_STACK and not (2 <= len(children) <= STACK_MAX_CHILDREN):
                        problem = 'Stack needs 2 or 3 nested buttons (got {}).'.format(len(children))
                    elif kind == TYPE_URLBUTTON and not url:
                        problem = 'URL Button needs a URL.'
                    elif kind == TYPE_SCRIPT and not (script_path and os.path.exists(script_path)):
                        problem = 'Pick a script.py file to import.'
                    elif target_panel is not None and \
                            os.path.exists(os.path.join(target_panel, folder_name)):
                        problem = u'Button Name Already Exists…'

            if problem:
                self._set_row_error(st, problem)
                any_error = True
                if first_bad is None:
                    first_bad = st['tb_name']
            else:
                plan.append({'name': name, 'type': kind, 'children': children,
                             'url': url, 'script_path': script_path})

        # Form-level issue: no panel to create into (rare — the picker defaults to one).
        if target_panel is None:
            self._set_global_error('Pick a target panel.')
            any_error = True

        if any_error:
            if first_bad is not None:
                first_bad.BringIntoView()   # surface the first flagged row
            return                          # block-all: fix everything, then Create

        self.target_panel_path = target_panel
        self.results = plan
        self.Close()


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ MAIN
#░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
#1️⃣ Paths
path_script     = os.path.abspath(__file__)                          # ...Development.panel/Button Generator.pushbutton/script.py
path_pushbutton = os.path.dirname(path_script)                       # ...Development.panel/Button Generator.pushbutton
path_template   = os.path.join(path_pushbutton, 'template')          # ...Development.panel/Button Generator.pushbutton/template
path_dev        = os.path.dirname(path_pushbutton)                   # ...Development.panel  (current panel)
path_tab        = os.path.dirname(path_dev)                          # ...tab folder
path_xaml_dir   = os.path.join(path_pushbutton, 'xaml')              # XAML files + title-bar icon live here
path_xaml       = os.path.join(path_xaml_dir, 'GeneratorForm.xaml')
path_icon       = os.path.join(path_pushbutton, 'icon.png')

#2️⃣ Check Panel Names (for dropdown)
# NOTE: Button Generator is restricted to generate buttons ONLY inside
#       Sandbox.panel — never in Tools.panel or any other panel.
#       The dropdown is hardcoded to a single choice: Sandbox.panel.
sandbox_panel_name = 'Sandbox.panel'
sandbox_panel_path = os.path.join(path_tab, sandbox_panel_name)
if not os.path.isdir(sandbox_panel_path):
    raise RuntimeError(
        'Button Generator requires a "Sandbox.panel" folder alongside the '
        'current tab. Please create it and try again.')
panel_choices  = [sandbox_panel_name]
current_panel  = sandbox_panel_name

#3️⃣ Show form, collect plan
form = GeneratorForm(path_xaml, path_tab, panel_choices, current_panel, icon_path=path_icon)
form.ShowDialog()

# Ensure Selection
if not form.results:
    script.exit()   # user cancelled

#4️⃣ Create everything inside the selected panel
target_panel = form.target_panel_path
log = []
for item in form.results:
    if   item['type'] == TYPE_PUSHBUTTON:
        create_pushbutton(target_panel, item['name'], log)
    elif item['type'] == TYPE_SCRIPT:
        create_scriptbutton(target_panel, item['name'], item['script_path'], log)
    elif item['type'] == TYPE_PULLDOWN:
        create_pulldown(target_panel,  item['name'], item['children'], log)
    elif item['type'] == TYPE_STACK:
        create_stack(target_panel,     item['name'], item['children'], log)
    elif item['type'] == TYPE_URLBUTTON:
        create_urlbutton(target_panel, item['name'], item['url'], log)

#5️⃣ Report
output = script.get_output()
output.close_others()
output.print_md('### PrasKaa Generator Report')
for line in log:
    print(line)

#6️⃣ Reload pyRevit
sessionmgr.reload_pyrevit()


#███████████████████████████████████████████████████████████████████████████
# Button Generator
