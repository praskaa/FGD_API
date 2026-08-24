# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import os
import ctypes

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

import System
from System.Windows              import (Window, Thickness, Visibility, WindowStyle,
                                          ResizeMode, SizeToContent, WindowStartupLocation,
                                          CornerRadius, TextWrapping, FontWeights)
from System.Windows.Controls     import (TreeViewItem, StackPanel, TextBlock, Orientation,
                                          ComboBoxItem, Border, Button)
from System.Windows.Media        import SolidColorBrush, ColorConverter
from System.Windows.Input        import MouseButtonState
from System.Windows.Interop      import WindowInteropHelper
from System.Windows.Threading    import DispatcherTimer
from System                      import TimeSpan, Action

from pyrevit.framework import wpf

import core
from settings import load_settings, save_settings
import view_actions

THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
XAML_PATH = os.path.join(THIS_DIR, u'browser.xaml')

_LIGHT_PALETTE = {
    'BgBrush': '#F2EDDC', 'PanelBrush': '#FFFFFF', 'BorderBrush1': '#D8D2BE',
    'TextBrush': '#0C3A52', 'SubTextBrush': '#6E93A0',
    'AccentBrush': '#0C4A63', 'AccentTextBrush': '#F2ECDC',
    'SelectedBrush': '#D9E3E6', 'HeaderBrush': '#E8E2CF',
    'RemoveBrush': '#EF4444', 'RemoveSoftBgBrush': '#FEE2E2',
    'OnLightBrush': '#0C3A52',
}
_DARK_PALETTE = {
    'BgBrush': '#0A3346', 'PanelBrush': '#0F5A78', 'BorderBrush1': '#1E6884',
    'TextBrush': '#F2ECDC', 'SubTextBrush': '#9FC3D1',
    'AccentBrush': '#2E93C7', 'AccentTextBrush': '#F2ECDC',
    'SelectedBrush': '#1B5C78', 'HeaderBrush': '#0A3F55',
    'RemoveBrush': '#F87171', 'RemoveSoftBgBrush': '#7A2E2E',
    'OnLightBrush': '#0C3A52',
}

# Badge colors reused per kind, just for the tree row prefix text.
KIND_LABEL = {
    core.KIND_TAB: 'TAB', core.KIND_PANEL: 'PANEL',
    core.KIND_PUSHBUTTON: 'BTN', core.KIND_URLBUTTON: 'URL',
    core.KIND_STACK: 'STACK', core.KIND_PULLDOWN: 'PULLDOWN',
    core.KIND_SMARTBUTTON: 'SMART',
}

# What a container of each kind is allowed to have created directly inside it.
# Tab -> only Panel. Panel -> the four leaf/container types. Stack/Pulldown ->
# only PushButton (nested containers inside a Stack/Pulldown aren't valid pyRevit).
CREATABLE_CHILDREN = {
    core.KIND_TAB:      [core.KIND_PANEL],
    core.KIND_PANEL:    [core.KIND_PUSHBUTTON, core.KIND_URLBUTTON, core.KIND_STACK, core.KIND_PULLDOWN],
    core.KIND_STACK:    [core.KIND_PUSHBUTTON, core.KIND_PULLDOWN],
    core.KIND_PULLDOWN: [core.KIND_PUSHBUTTON],
}

ADD_NEW_LABEL = {
    core.KIND_TAB:      'ADD NEW PANEL',
    core.KIND_PANEL:    'ADD NEW ITEM',
    core.KIND_STACK:    'ADD NEW ITEM (nested)',
    core.KIND_PULLDOWN: 'ADD NEW BUTTON (nested)',
}


class BrowserWindow(Window):

    def __init__(self, path_extension, splash=None, splash_start=None):
        self.path_extension = path_extension
        self._dark_mode      = load_settings().get('dark_mode', False)
        self._selected_node   = None
        self._tabs            = []
        self._new_kind        = None   # currently chosen type in the Add New badges
        self._new_allowed     = []
        self._suppress_slideout_event = False
        self._collapsed_paths = set()  # node.path values the user explicitly collapsed

        wpf.LoadComponent(self, XAML_PATH)

        # MUST run here, synchronously, while __init__ is still inside the
        # Revit API context of the button click that opened this window.
        view_actions.init_events(on_reload_done=self._on_reload_finished)

        self.SourceInitialized += self._on_source_initialized
        self.titleBar.MouseLeftButtonDown += self._on_titlebar_drag

        self._wire_events()
        self._apply_palette(_DARK_PALETTE if self._dark_mode else _LIGHT_PALETTE)
        self.cb_AlwaysOnTop.IsChecked = load_settings().get('always_on_top', False)
        self.Topmost = False  # keep off while splash is up

        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromMilliseconds(50)

        def _first_build(sender, args):
            timer.Stop()
            self._reload_tree()
            if splash is not None:
                splash.Close()
            self.Topmost = bool(self.cb_AlwaysOnTop.IsChecked)

        timer.Tick += _first_build
        timer.Start()

    # ---- chrome ------------------------------------------------------
    def _on_titlebar_drag(self, sender, args):
        if args.LeftButton == MouseButtonState.Pressed:
            self.DragMove()

    def _on_source_initialized(self, sender, args):
        self._apply_titlebar_theme(self._dark_mode)

    def _apply_titlebar_theme(self, dark):
        try:
            hwnd = WindowInteropHelper(self).Handle
            value = ctypes.c_int(1 if dark else 0)
            for attr in (20, 19):
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd.ToInt64()), attr, ctypes.byref(value), ctypes.sizeof(value))
                if result == 0:
                    break
        except Exception:
            pass

    def _wire_events(self):
        self.btn_Close.Click          += lambda s, a: self.Close()
        self.btn_ThemeToggle.Click    += self._on_theme_toggle
        self.cb_AlwaysOnTop.Checked   += self._on_always_on_top_changed
        self.cb_AlwaysOnTop.Unchecked += self._on_always_on_top_changed
        self.btn_Refresh.Click        += lambda s, a: self._reload_tree()
        self.btn_Diagnose.Click       += self._on_diagnose_click
        self.btn_ReloadPyrevit.Click  += self._on_reload_pyrevit
        self.tv_Tree.SelectedItemChanged += self._on_tree_selection_changed
        self.tb_Search.TextChanged    += self._on_search_changed

        self.btn_Rename.Click  += self._on_rename_click
        self.btn_MoveUp.Click  += lambda s, a: self._on_reorder_click(-1)
        self.btn_MoveDown.Click += lambda s, a: self._on_reorder_click(1)
        self.btn_MoveTo.Click  += self._on_move_click
        self.btn_Delete.Click  += self._on_delete_click
        self.cb_Slideout.Checked   += self._on_slideout_changed
        self.cb_Slideout.Unchecked += self._on_slideout_changed

        self._new_badges = {
            core.KIND_PUSHBUTTON: (self.badge_New_PushButton, self.lbl_New_PushButton),
            core.KIND_URLBUTTON:  (self.badge_New_URLButton,  self.lbl_New_URLButton),
            core.KIND_STACK:      (self.badge_New_Stack,      self.lbl_New_Stack),
            core.KIND_PULLDOWN:   (self.badge_New_Pulldown,   self.lbl_New_Pulldown),
        }
        for kind, (bd, _) in self._new_badges.items():
            def on_click(s, a, k=kind):
                self._select_new_kind(k)
                a.Handled = True
            bd.MouseLeftButtonDown += on_click

        self.btn_CreateNew.Click += self._on_create_new_click

    # ---- theme ---------------------------------------------------------
    def _on_theme_toggle(self, sender, args):
        self._dark_mode = not self._dark_mode
        self._apply_palette(_DARK_PALETTE if self._dark_mode else _LIGHT_PALETTE)
        self._apply_titlebar_theme(self._dark_mode)
        save_settings({'dark_mode': self._dark_mode})

    def _apply_palette(self, palette):
        for key, hex_c in palette.items():
            self.Resources[key] = SolidColorBrush(ColorConverter.ConvertFromString(hex_c))

    def _on_always_on_top_changed(self, sender, args):
        self.Topmost = bool(self.cb_AlwaysOnTop.IsChecked)
        save_settings({'always_on_top': self.Topmost})

    # ---- tree building ---------------------------------------------------
    def _reload_tree(self):
        selected_path = self._selected_node.path if self._selected_node else None
        self._tabs = core.scan_extension(self.path_extension)
        self.tv_Tree.Items.Clear()

        for tab_node in self._tabs:
            self.tv_Tree.Items.Add(self._build_tree_item(tab_node))

        self._populate_move_targets()
        self._selected_node = None
        self.tb_SelectedPath.Text = 'Nothing selected'
        self._set_actions_enabled(False)

        if selected_path:
            self._reselect_by_path(selected_path)

        if self.tb_Search.Text:
            self._on_search_changed(None, None)

        self._set_status('Loaded {} tab(s).'.format(len(self._tabs)))

    def _build_tree_item(self, node):
        item = TreeViewItem()
        item.Header = self._row_header(node)
        item.Tag    = node
        item.IsExpanded = node.path not in self._collapsed_paths

        def on_expanded(s, a, it=item, n=node):
            if s is it:
                self._collapsed_paths.discard(n.path)
        def on_collapsed(s, a, it=item, n=node):
            if s is it:
                self._collapsed_paths.add(n.path)
        item.Expanded  += on_expanded
        item.Collapsed += on_collapsed

        for child in node.children:
            item.Items.Add(self._build_tree_item(child))
        return item

    def _row_header(self, node):
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        label = TextBlock()
        label.Text = '[{}] '.format(KIND_LABEL.get(node.kind, node.kind.upper()))
        label.SetResourceReference(TextBlock.ForegroundProperty, 'SubTextBrush')
        label.FontSize = 10
        name = TextBlock()
        name.Text = node.display_name
        name.SetResourceReference(TextBlock.ForegroundProperty, 'TextBrush')
        panel.Children.Add(label)
        panel.Children.Add(name)

        if node.kind in (core.KIND_STACK, core.KIND_PULLDOWN) and not node.children:
            warn = TextBlock()
            warn.Text = '  (empty — will break on reload)'
            warn.FontSize = 10
            warn.FontStyle = System.Windows.FontStyles.Italic
            warn.SetResourceReference(TextBlock.ForegroundProperty, 'RemoveBrush')
            panel.Children.Add(warn)

        return panel

    def _reselect_by_path(self, path):
        def walk(items, ancestors):
            for item in items:
                node = item.Tag
                if node is not None and node.path == path:
                    # Force every ancestor open so the moved/reordered item
                    # is actually visible, not just "selected" off-screen.
                    for anc_item, anc_node in ancestors:
                        anc_item.IsExpanded = True
                        self._collapsed_paths.discard(anc_node.path)
                    item.IsSelected = True

                    def _focus(it=item):
                        it.BringIntoView()
                        it.Focus()
                    self.Dispatcher.BeginInvoke(Action(_focus))
                    return True
                if walk(item.Items, ancestors + [(item, node)]):
                    return True
            return False
        walk(self.tv_Tree.Items, [])

    # ---- search filter -------------------------------------------------
    def _on_search_changed(self, sender, args):
        query = (self.tb_Search.Text or '').strip().lower()
        for item in self.tv_Tree.Items:
            self._apply_search_filter(item, query)

    def _apply_search_filter(self, item, query):
        """Recursively hide tree rows that don't match, keep a row visible
        if any descendant matches, and auto-expand containers that only
        show up because a descendant matched (so the match is reachable)."""
        node = item.Tag
        self_match = (not query) or (query in node.display_name.lower())

        child_match = False
        for child_item in item.Items:
            if self._apply_search_filter(child_item, query):
                child_match = True

        visible = self_match or child_match
        item.Visibility = Visibility.Visible if visible else Visibility.Collapsed

        if query:
            if child_match:
                item.IsExpanded = True
        else:
            item.IsExpanded = node.path not in self._collapsed_paths

        return visible

    # ---- selection ---------------------------------------------------
    def _on_tree_selection_changed(self, sender, args):
        item = self.tv_Tree.SelectedItem
        node = item.Tag if item is not None else None
        self._selected_node = node
        if node is None:
            self.tb_SelectedPath.Text = 'Nothing selected'
            self._set_actions_enabled(False)
            return

        self.tb_SelectedPath.Text = u'{}\n{}'.format(node.display_name, node.path)
        self.tb_RenameInput.Text = node.display_name
        manageable = node.kind in core.MANAGEABLE_KINDS

        # Existing-item actions (rename/reorder/move/delete) only apply to
        # something that isn't the Tab itself (Tab reorder/move is out of scope).
        self.sp_ExistingActions.Visibility = Visibility.Visible if manageable else Visibility.Collapsed
        self._set_actions_enabled(manageable)

        # Slide-out checkbox reflects current placement; only meaningful
        # when the item actually has a parent panel/container.
        self._suppress_slideout_event = True
        if manageable and node.parent is not None:
            self.cb_Slideout.IsEnabled = True
            self.cb_Slideout.IsChecked = core.get_slideout_state(node.parent, core.strip_suffix(node.name))
        else:
            self.cb_Slideout.IsEnabled = False
            self.cb_Slideout.IsChecked = False
        self._suppress_slideout_event = False

        # Contextual "Add New" section — only for containers.
        self._update_add_new_section(node)

    def _set_actions_enabled(self, enabled):
        for ctrl in (self.tb_RenameInput, self.btn_Rename, self.btn_MoveUp,
                     self.btn_MoveDown, self.cb_MoveTarget, self.btn_MoveTo,
                     self.btn_Delete):
            ctrl.IsEnabled = enabled

    # ---- contextual "Add New" -----------------------------------------
    def _update_add_new_section(self, node):
        allowed = CREATABLE_CHILDREN.get(node.kind, [])
        self._new_allowed = allowed

        if not allowed:
            self.sp_AddNewSection.Visibility = Visibility.Collapsed
            self.sep_AddNew.Visibility = Visibility.Collapsed
            return

        self.sp_AddNewSection.Visibility = Visibility.Visible
        self.sep_AddNew.Visibility = Visibility.Visible
        self.tb_AddNewHeader.Text = ADD_NEW_LABEL.get(node.kind, 'ADD NEW')
        self.tb_NewName.Text = ''
        self.tb_NewUrl.Text = ''
        self.tb_AddNewError.Visibility = Visibility.Collapsed

        if len(allowed) > 1:
            self.wp_NewTypeBadges.Visibility = Visibility.Visible
            for kind, (bd, _) in self._new_badges.items():
                bd.Visibility = Visibility.Visible if kind in allowed else Visibility.Collapsed
            self._select_new_kind(allowed[0])
        else:
            # Only one valid type here — skip the badge picker entirely,
            # the user shouldn't have to choose something with one option.
            self.wp_NewTypeBadges.Visibility = Visibility.Collapsed
            self._select_new_kind(allowed[0])

    def _select_new_kind(self, kind):
        self._new_kind = kind
        for k, (bd, lb) in self._new_badges.items():
            if k == kind:
                bd.Style = bd.FindResource('NewBadgeSelected')
                lb.Style = lb.FindResource('NewBadgeTextSelected')
            else:
                bd.Style = bd.FindResource('NewBadgeUnselected')
                lb.Style = lb.FindResource('NewBadgeTextUnselected')

        is_url = (kind == core.KIND_URLBUTTON)
        self.tb_NewUrl.Visibility     = Visibility.Visible if is_url else Visibility.Collapsed
        self.tb_NewUrlHint.Visibility = Visibility.Visible if is_url else Visibility.Collapsed
        self.tb_AddNewError.Visibility = Visibility.Collapsed

    # ---- move-target dropdown ---------------------------------------
    def _populate_move_targets(self):
        self.cb_MoveTarget.Items.Clear()

        def walk(node):
            if node.kind in core.CONTAINER_KINDS:
                full = node.kind == core.KIND_STACK and len(node.children) >= core.STACK_MAX_CHILDREN
                cbi = ComboBoxItem()
                cbi.Content = self._path_label(node) + (u'  (full)' if full else u'')
                cbi.Tag = node
                cbi.IsEnabled = not full
                self.cb_MoveTarget.Items.Add(cbi)
            for child in node.children:
                walk(child)

        for tab_node in self._tabs:
            walk(tab_node)

    def _path_label(self, node):
        parts = []
        n = node
        while n is not None:
            parts.append(n.display_name)
            n = n.parent
        return u' / '.join(reversed(parts))

    # ---- actions -------------------------------------------------------
    def _on_rename_click(self, sender, args):
        if self._selected_node is None:
            return
        new_name = self.tb_RenameInput.Text
        try:
            core.rename_bundle(self._selected_node, new_name)
            self._set_status(u'Renamed to "{}".'.format(new_name))
        except core.OpError as e:
            self._set_status(u'Rename failed: {}'.format(str(e)), error=True)
            return
        self._reload_tree()

    def _on_reorder_click(self, direction):
        node = self._selected_node
        if node is None or node.parent is None:
            return
        siblings = [core.strip_suffix(c.name) for c in node.parent.children]
        current_display = core.strip_suffix(node.name)
        new_order = core.move_row(node.parent.path, siblings, current_display, direction)
        core.apply_layout(node.parent.path, new_order)
        self._set_status(u'Reordered "{}".'.format(node.display_name))
        self._reload_tree()

    def _on_move_click(self, sender, args):
        node = self._selected_node
        target_item = self.cb_MoveTarget.SelectedItem
        if node is None or target_item is None:
            return
        target_node = target_item.Tag
        try:
            core.move_bundle(node, target_node)
            self._set_status(u'Moved "{}" to "{}".'.format(node.display_name, target_node.display_name))
        except core.OpError as e:
            self._set_status(u'Move failed: {}'.format(str(e)), error=True)
            return
        self._reload_tree()

    def _on_slideout_changed(self, sender, args):
        if self._suppress_slideout_event:
            return
        node = self._selected_node
        if node is None or node.parent is None:
            return
        want_slideout = bool(self.cb_Slideout.IsChecked)
        core.set_slideout(node.parent, core.strip_suffix(node.name), want_slideout)
        self._set_status(u'{} is {} the slide-out.'.format(
            node.display_name, 'now in' if want_slideout else 'no longer in'))
        self._reload_tree()

    def _on_delete_click(self, sender, args):
        node = self._selected_node
        if node is None:
            return
        confirmed = self._confirm(
            u'Delete "{}"?'.format(node.display_name),
            u'This permanently removes it and everything inside it. This cannot be undone.')
        if not confirmed:
            return
        core.delete_bundle(node)
        self._set_status(u'Deleted "{}".'.format(node.display_name))
        self._reload_tree()

    def _confirm(self, title, message, confirm_text='Delete', confirm_style='DangerButtonStyle'):
        """Small Yes/No dialog, owned by this window so it stays on top of
        it and returns focus here on close — forms.alert() has no Owner and
        was causing the main window to lose focus/minimize behind Revit."""
        dlg = Window()
        dlg.Owner = self
        dlg.Title = title
        dlg.WindowStartupLocation = WindowStartupLocation.CenterOwner
        dlg.WindowStyle = getattr(WindowStyle, 'None')  # 'None' is a Python keyword, can't dot-access it
        dlg.ResizeMode = ResizeMode.NoResize
        dlg.SizeToContent = SizeToContent.WidthAndHeight
        dlg.Topmost = True
        dlg.Background = self.Resources['PanelBrush']

        outer = Border()
        outer.BorderBrush = self.Resources['BorderBrush1']
        outer.BorderThickness = Thickness(1)
        outer.CornerRadius = CornerRadius(8)
        outer.Padding = Thickness(20)
        outer.MinWidth = 340
        outer.MaxWidth = 420

        panel = StackPanel()
        title_tb = TextBlock()
        title_tb.Text = title
        title_tb.FontSize = 14
        title_tb.FontWeight = FontWeights.SemiBold
        title_tb.SetResourceReference(TextBlock.ForegroundProperty, 'TextBrush')
        title_tb.Margin = Thickness(0, 0, 0, 8)
        title_tb.TextWrapping = TextWrapping.Wrap

        msg_tb = TextBlock()
        msg_tb.Text = message
        msg_tb.FontSize = 12
        msg_tb.SetResourceReference(TextBlock.ForegroundProperty, 'SubTextBrush')
        msg_tb.TextWrapping = TextWrapping.Wrap
        msg_tb.Margin = Thickness(0, 0, 0, 18)

        btn_row = StackPanel()
        btn_row.Orientation = Orientation.Horizontal
        btn_row.HorizontalAlignment = System.Windows.HorizontalAlignment.Right

        result = {'value': False}

        btn_cancel = Button()
        btn_cancel.Content = 'Cancel'
        btn_cancel.Style = self.FindResource('ToolButtonStyle')
        btn_cancel.Margin = Thickness(0, 0, 8, 0)
        btn_cancel.Click += lambda s, a: (result.__setitem__('value', False), dlg.Close())

        btn_confirm = Button()
        btn_confirm.Content = confirm_text
        btn_confirm.Style = self.FindResource(confirm_style)
        btn_confirm.Click += lambda s, a: (result.__setitem__('value', True), dlg.Close())

        btn_row.Children.Add(btn_cancel)
        btn_row.Children.Add(btn_confirm)

        panel.Children.Add(title_tb)
        panel.Children.Add(msg_tb)
        panel.Children.Add(btn_row)
        outer.Child = panel
        dlg.Content = outer

        dlg.ShowDialog()
        return result['value']

    def _on_create_new_click(self, sender, args):
        node = self._selected_node
        if node is None or self._new_kind is None:
            return

        name = self.tb_NewName.Text
        kind = self._new_kind

        # Stack has a hard child cap in pyRevit — warn before hitting the
        # filesystem, same rule the button Generator already enforces.
        if node.kind == core.KIND_STACK and len(node.children) >= core.STACK_MAX_CHILDREN:
            self._show_add_new_error('Stack already has the maximum of {} nested buttons.'.format(
                core.STACK_MAX_CHILDREN))
            return

        try:
            if kind == core.KIND_PANEL:
                core.create_panel(node.path, name)
            elif kind == core.KIND_PUSHBUTTON:
                core.create_pushbutton(node.path, name)
            elif kind == core.KIND_URLBUTTON:
                core.create_urlbutton(node.path, name, self.tb_NewUrl.Text)
            elif kind == core.KIND_STACK:
                core.create_stack(node.path, name)
            elif kind == core.KIND_PULLDOWN:
                core.create_pulldown(node.path, name)
        except core.OpError as e:
            self._show_add_new_error(str(e))
            return

        self._set_status(u'Created "{}".'.format(name.strip()))
        self._reload_tree()

    def _show_add_new_error(self, message):
        self.tb_AddNewError.Text = message
        self.tb_AddNewError.Visibility = Visibility.Visible

    def _on_diagnose_click(self, sender, args):
        # Re-scan fresh so results reflect anything just edited, not stale state.
        tabs = core.scan_extension(self.path_extension)
        issues = core.run_diagnostics(self.path_extension, tabs)

        if not issues:
            self._info('All clear', 'No known pyRevit-breaking issues found in this extension.')
            self._set_status('Diagnose: no issues found.')
            return

        lines = []
        for path, msg in issues:
            rel = path[len(self.path_extension):].lstrip('\\/') if path.startswith(self.path_extension) else path
            lines.append(u'• {}\n   {}'.format(rel, msg))
        self._info(u'{} issue(s) found'.format(len(issues)), u'\n\n'.join(lines))
        self._set_status(u'Diagnose: {} issue(s) found — see dialog.'.format(len(issues)), error=True)

    def _info(self, title, message):
        """Single-button (OK) informational dialog, owned by this window,
        with a scrollable body for longer diagnostic reports."""
        dlg = Window()
        dlg.Owner = self
        dlg.Title = title
        dlg.WindowStartupLocation = WindowStartupLocation.CenterOwner
        dlg.WindowStyle = getattr(WindowStyle, 'None')
        dlg.ResizeMode = ResizeMode.NoResize
        dlg.SizeToContent = SizeToContent.WidthAndHeight
        dlg.Topmost = True
        dlg.Background = self.Resources['PanelBrush']

        outer = Border()
        outer.BorderBrush = self.Resources['BorderBrush1']
        outer.BorderThickness = Thickness(1)
        outer.CornerRadius = CornerRadius(8)
        outer.Padding = Thickness(20)
        outer.MinWidth = 380
        outer.MaxWidth = 560

        panel = StackPanel()
        title_tb = TextBlock()
        title_tb.Text = title
        title_tb.FontSize = 14
        title_tb.FontWeight = FontWeights.SemiBold
        title_tb.SetResourceReference(TextBlock.ForegroundProperty, 'TextBrush')
        title_tb.Margin = Thickness(0, 0, 0, 10)
        title_tb.TextWrapping = TextWrapping.Wrap

        scroller = System.Windows.Controls.ScrollViewer()
        scroller.MaxHeight = 340
        scroller.VerticalScrollBarVisibility = System.Windows.Controls.ScrollBarVisibility.Auto

        msg_tb = TextBlock()
        msg_tb.Text = message
        msg_tb.FontSize = 12
        msg_tb.FontFamily = System.Windows.Media.FontFamily('Consolas')
        msg_tb.SetResourceReference(TextBlock.ForegroundProperty, 'SubTextBrush')
        msg_tb.TextWrapping = TextWrapping.Wrap
        scroller.Content = msg_tb

        btn_row = StackPanel()
        btn_row.Orientation = Orientation.Horizontal
        btn_row.HorizontalAlignment = System.Windows.HorizontalAlignment.Right
        btn_row.Margin = Thickness(0, 16, 0, 0)

        btn_ok = Button()
        btn_ok.Content = 'OK'
        btn_ok.Style = self.FindResource('PrimaryButtonStyle')
        btn_ok.Click += lambda s, a: dlg.Close()
        btn_row.Children.Add(btn_ok)

        panel.Children.Add(title_tb)
        panel.Children.Add(scroller)
        panel.Children.Add(btn_row)
        outer.Child = panel
        dlg.Content = outer

        dlg.ShowDialog()

    def _on_reload_pyrevit(self, sender, args):
        empties = core.find_empty_containers(self._tabs)
        if empties:
            names = u', '.join(n.display_name for n in empties)
            proceed = self._confirm(
                u'{} empty Stack/Pulldown found'.format(len(empties)),
                u'pyRevit can\'t build a ribbon button for an empty Stack or '
                u'Pulldown, and will error on this panel: {}. Add at least '
                u'one PushButton inside each first, or delete them — '
                u'otherwise this may break the panel on reload.'.format(names),
                confirm_text='Reload Anyway', confirm_style='PrimaryButtonStyle')
            if not proceed:
                return

        self._set_status('Reloading pyRevit...')
        self.btn_ReloadPyrevit.IsEnabled = False
        view_actions.request_reload()   # queued on Revit's thread, not run here

    def _on_reload_finished(self):
        """Runs on Revit's thread (inside ExternalEvent.Execute). Marshal
        back to the WPF thread before touching any UI control."""
        def _update():
            self.btn_ReloadPyrevit.IsEnabled = True
            self._set_status('pyRevit reloaded.')
        self.Dispatcher.Invoke(Action(_update))

    def _set_status(self, message, error=False):
        self.tb_Status.Text = message
        self.tb_Status.SetResourceReference(
            TextBlock.ForegroundProperty, 'RemoveBrush' if error else 'SubTextBrush')
