# Copyright (C) 2002-2006 Stephen Kennedy <stevek@gnome.org>
# Copyright (C) 2010-2013 Kai Willadsen <kai.willadsen@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or (at
# your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk

import meld.ui.util
from meld.conf import _, ui_file
from meld.dirdiff import DirDiff
from meld.filediff import FileDiff
from meld.filemerge import FileMerge
from meld.melddoc import ComparisonState, MeldDoc
from meld.newdifftab import NewDiffTab
from meld.recent import recent_comparisons, RecentType
from meld.task import LifoScheduler
from meld.ui._gtktemplate import Template
from meld.ui.notebooklabel import NotebookLabel
from meld.vcview import VcView
from meld.windowstate import SavedWindowState


@Template(resource_path='/org/gnome/meld/ui/appwindow.ui')
class MeldWindow(Gtk.ApplicationWindow):

    __gtype_name__ = 'MeldWindow'

    appvbox = Template.Child("appvbox")
    gear_menu_button = Template.Child("gear_menu_button")
    notebook = Template.Child("notebook")
    spinner = Template.Child("spinner")
    toolbar_holder = Template.Child("toolbar_holder")

    def __init__(self):
        super().__init__()

        self.init_template()

        try:
            from Cocoa import NSApp
            self.is_quartz = True
        except:
            self.is_quartz = False

        actions = (
            ("FileMenu", None, _("_File")),
            ("New", Gtk.STOCK_NEW, _("_New Comparison…"), "<Primary>N",
                _("Start a new comparison"),
                self.on_menu_file_new_activate),
            ("Save", Gtk.STOCK_SAVE, None, None,
                _("Save the current file"),
                self.on_menu_save_activate),
            ("SaveAs", Gtk.STOCK_SAVE_AS, _("Save As…"), "<Primary><shift>S",
                _("Save the current file with a different name"),
                self.on_menu_save_as_activate),
            ("Close", Gtk.STOCK_CLOSE, None, None,
                _("Close the current file"),
                self.on_menu_close_activate),

            ("EditMenu", None, _("_Edit")),
            ("Undo", Gtk.STOCK_UNDO, None, "<Primary>Z",
                _("Undo the last action"),
                self.on_menu_undo_activate),
            ("Redo", Gtk.STOCK_REDO, None, "<Primary><shift>Z",
                _("Redo the last undone action"),
                self.on_menu_redo_activate),
            ("Cut", Gtk.STOCK_CUT, None, None, _("Cut the selection"),
                self.on_menu_cut_activate),
            ("Copy", Gtk.STOCK_COPY, None, None, _("Copy the selection"),
                self.on_menu_copy_activate),
            ("Paste", Gtk.STOCK_PASTE, None, None, _("Paste the clipboard"),
                self.on_menu_paste_activate),
            ("Find", Gtk.STOCK_FIND, _("Find…"), None, _("Search for text"),
                self.on_menu_find_activate),
            ("FindNext", None, _("Find Ne_xt"), "<Primary>G",
                _("Search forwards for the same text"),
                self.on_menu_find_next_activate),
            ("FindPrevious", None, _("Find _Previous"), "<Primary><shift>G",
                _("Search backwards for the same text"),
                self.on_menu_find_previous_activate),
            ("Replace", Gtk.STOCK_FIND_AND_REPLACE,
                _("_Replace…"), "<Primary>H",
                _("Find and replace text"),
                self.on_menu_replace_activate),
            ("GoToLine", None, _("Go to _Line"), "<Primary>I",
                _("Go to a specific line"),
                self.on_menu_go_to_line_activate),

            ("ChangesMenu", None, _("_Changes")),
            ("NextChange", Gtk.STOCK_GO_DOWN, _("Next Change"), "<Alt>Down",
                _("Go to the next change"),
                self.on_menu_edit_down_activate),
            ("PrevChange", Gtk.STOCK_GO_UP, _("Previous Change"), "<Alt>Up",
                _("Go to the previous change"),
                self.on_menu_edit_up_activate),
            ("OpenExternal", None, _("Open Externally"), None,
                _("Open selected file or directory in the default external "
                  "application"),
                self.on_open_external),

            ("ViewMenu", None, _("_View")),
            ("FileStatus", None, _("File Status")),
            ("VcStatus", None, _("Version Status")),
            ("FileFilters", None, _("File Filters")),
            ("Stop", Gtk.STOCK_STOP, None, "Escape",
                _("Stop the current action"),
                self.on_toolbar_stop_clicked),
            ("Refresh", Gtk.STOCK_REFRESH, None, "<Primary>R",
                _("Refresh the view"),
                self.on_menu_refresh_activate),
        )
        toggleactions = (
            ("Fullscreen", None, _("Fullscreen"), "F11",
                _("View the comparison in fullscreen"),
                self.on_action_fullscreen_toggled, False),
        )
        self.actiongroup = Gtk.ActionGroup(name='MainActions')
        self.actiongroup.set_translation_domain("meld")
        self.actiongroup.add_actions(actions)
        self.actiongroup.add_toggle_actions(toggleactions)

        recent_action = Gtk.RecentAction(
            name="Recent",  label=_("Open Recent"),
            tooltip=_("Open recent files"), stock_id=None)
        recent_action.set_show_private(True)
        recent_action.set_filter(recent_comparisons.recent_filter)
        recent_action.set_sort_type(Gtk.RecentSortType.MRU)
        recent_action.connect("item-activated", self.on_action_recent)
        self.actiongroup.add_action(recent_action)

        self.ui = Gtk.UIManager()
        self.ui.insert_action_group(self.actiongroup, 0)
        self.ui.add_ui_from_file(ui_file("meldapp-ui.xml"))

        for menuitem in ("Save", "Undo"):
            self.actiongroup.get_action(menuitem).props.is_important = True
        self.add_accel_group(self.ui.get_accel_group())
        self.menubar = self.ui.get_widget('/Menubar')
        self.toolbar = self.ui.get_widget('/Toolbar')
        self.toolbar.get_style_context().add_class(
            Gtk.STYLE_CLASS_PRIMARY_TOOLBAR)

        if self.is_quartz:
            self.menubar.hide()
            self.quartz_ready = False
            self.connect('window_state_event', self.osx_menu_setup)

        # Alternate keybindings for a few commands.
        extra_accels = (
            ("<Primary>D", self.on_menu_edit_down_activate),
            ("<Primary>E", self.on_menu_edit_up_activate),
            ("<Alt>KP_Down", self.on_menu_edit_down_activate),
            ("<Alt>KP_Up", self.on_menu_edit_up_activate),
            ("F5", self.on_menu_refresh_activate),
        )

        accel_group = self.ui.get_accel_group()
        for accel, callback in extra_accels:
            keyval, mask = Gtk.accelerator_parse(accel)
            accel_group.connect(keyval, mask, 0, callback)

        # Initialise sensitivity for important actions
        self.actiongroup.get_action("Stop").set_sensitive(False)
        self._update_page_action_sensitivity()

        self.appvbox.pack_start(self.menubar, False, True, 0)
        self.toolbar_holder.pack_start(self.toolbar, True, True, 0)

        # This double toolbar works around integrating non-UIManager widgets
        # into the toolbar. It's no longer used, but kept as a possible
        # GAction porting helper.
        self.secondary_toolbar = Gtk.Toolbar()
        self.secondary_toolbar.get_style_context().add_class(
            Gtk.STYLE_CLASS_PRIMARY_TOOLBAR)
        self.toolbar_holder.pack_end(self.secondary_toolbar, False, True, 0)
        self.secondary_toolbar.show_all()

        # Manually handle GAction additions
        actions = (
            ("close", self.on_menu_close_activate, None),
        )
        for (name, callback, accel) in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', callback)
            self.add_action(action)

        # Fake out the spinner on Windows. See Gitlab issue #133.
        if os.name == 'nt':
            for attr in ('stop', 'hide', 'show', 'start'):
                setattr(self.spinner, attr, lambda *args: True)

        self.drag_dest_set(
            Gtk.DestDefaults.MOTION | Gtk.DestDefaults.HIGHLIGHT |
            Gtk.DestDefaults.DROP,
            None, Gdk.DragAction.COPY)
        self.drag_dest_add_uri_targets()
        self.connect(
            "drag_data_received", self.on_widget_drag_data_received)

        self.window_state = SavedWindowState()
        self.window_state.bind(self)

        self.should_close = False
        self.idle_hooked = 0
        self.scheduler = LifoScheduler()
        self.scheduler.connect("runnable", self.on_scheduler_runnable)

        self.ui.ensure_update()
        self.diff_handler = None
        self.undo_handlers = tuple()
        # Set tooltip on map because the recentmenu is lazily created
        rmenu = self.ui.get_widget('/Menubar/FileMenu/Recent').get_submenu()
        rmenu.connect("map", self._on_recentmenu_map)

    def do_realize(self):
        Gtk.ApplicationWindow.do_realize(self)

        app = self.get_application()
        menu = app.get_menu_by_id("gear-menu")

        # For some reason, this is broken on Mac. Let's build the menu manually
        if self.is_quartz:
            builder = Gtk.Builder.new_from_resource(
                '/org/gnome/meld/gtk/menus.ui')
            menu = builder.get_object('gear-menu')

        self.gear_menu_button.set_popover(
            Gtk.Popover.new_from_model(self.gear_menu_button, menu))

        meld.ui.util.extract_accels_from_menu(menu, self.get_application())

    def osx_menu_setup(self, widget, event, callback_data=None):
        if self.quartz_ready == False:
            self.get_application().setup_mac_integration(self.menubar)
            self.quartz_ready = True

    def osx_dock_bounce(self):
        import gi
        gi.require_version('GtkosxApplication', '1.0') 
        from gi.repository import GtkosxApplication as gtkosx_application
        macapp = gtkosx_application.Application()
        macapp.attention_request(gtkosx_application.ApplicationAttentionType.NFO_REQUEST)

    def _on_recentmenu_map(self, recentmenu):
        for imagemenuitem in recentmenu.get_children():
            imagemenuitem.set_tooltip_text(imagemenuitem.get_label())

    def on_widget_drag_data_received(
            self, wid, context, x, y, selection_data, info, time):
        uris = selection_data.get_uris()
        if uris:
            self.open_paths([Gio.File.new_for_uri(uri) for uri in uris])
            return True

    def on_idle(self):
        ret = self.scheduler.iteration()
        if ret and isinstance(ret, str):
            self.spinner.set_tooltip_text(ret)

        pending = self.scheduler.tasks_pending()
        if not pending:
            self.spinner.stop()
            self.spinner.hide()
            self.spinner.set_tooltip_text("")
            self.idle_hooked = None
            self.actiongroup.get_action("Stop").set_sensitive(False)
            if self.is_quartz:
                self.osx_dock_bounce()
        return pending

    def on_scheduler_runnable(self, sched):
        if not self.idle_hooked:
            self.spinner.show()
            self.spinner.start()
            self.actiongroup.get_action("Stop").set_sensitive(True)
            self.idle_hooked = GLib.idle_add(self.on_idle)

    @Template.Callback()
    def on_delete_event(self, *extra):
        should_cancel = False
        # Delete pages from right-to-left.  This ensures that if a version
        # control page is open in the far left page, it will be closed last.
        for page in reversed(self.notebook.get_children()):
            self.notebook.set_current_page(self.notebook.page_num(page))
            response = page.on_delete_event()
            if response == Gtk.ResponseType.CANCEL:
                should_cancel = True

        should_cancel = should_cancel or self.has_pages()
        if should_cancel:
            self.should_close = True
        return should_cancel

    def has_pages(self):
        return self.notebook.get_n_pages() > 0

    def _update_page_action_sensitivity(self):
        current_page = self.notebook.get_current_page()

        if current_page != -1:
            page = self.notebook.get_nth_page(current_page)
        else:
            page = None

        self.actiongroup.get_action("Close").set_sensitive(bool(page))
        if not isinstance(page, MeldDoc):
            for action in ("PrevChange", "NextChange", "Cut", "Copy", "Paste",
                           "Find", "FindNext", "FindPrevious", "Replace",
                           "Refresh", "GoToLine"):
                self.actiongroup.get_action(action).set_sensitive(False)
        else:
            for action in ("Find", "Refresh"):
                self.actiongroup.get_action(action).set_sensitive(True)
            is_filediff = isinstance(page, FileDiff)
            for action in ("Cut", "Copy", "Paste", "FindNext", "FindPrevious",
                           "Replace", "GoToLine"):
                self.actiongroup.get_action(action).set_sensitive(is_filediff)

    def handle_current_doc_switch(self, page):
        if self.diff_handler is not None:
            page.disconnect(self.diff_handler)
        page.on_container_switch_out_event(self.ui)
        if self.undo_handlers:
            undoseq = page.undosequence
            for handler in self.undo_handlers:
                undoseq.disconnect(handler)
            self.undo_handlers = tuple()

    @Template.Callback()
    def on_switch_page(self, notebook, page, which):
        oldidx = notebook.get_current_page()
        if oldidx >= 0:
            olddoc = notebook.get_nth_page(oldidx)
            self.handle_current_doc_switch(olddoc)

        newdoc = notebook.get_nth_page(which) if which >= 0 else None
        try:
            undoseq = newdoc.undosequence
            can_undo = undoseq.can_undo()
            can_redo = undoseq.can_redo()
            undo_handler = undoseq.connect("can-undo", self.on_can_undo)
            redo_handler = undoseq.connect("can-redo", self.on_can_redo)
            self.undo_handlers = (undo_handler, redo_handler)
        except AttributeError:
            can_undo, can_redo = False, False
        self.actiongroup.get_action("Undo").set_sensitive(can_undo)
        self.actiongroup.get_action("Redo").set_sensitive(can_redo)

        # FileDiff handles save sensitivity; it makes no sense for other modes
        if not isinstance(newdoc, FileDiff):
            self.actiongroup.get_action("Save").set_sensitive(False)
            self.actiongroup.get_action("SaveAs").set_sensitive(False)
        else:
            self.actiongroup.get_action("SaveAs").set_sensitive(True)

        if newdoc:
            nbl = self.notebook.get_tab_label(newdoc)
            self.set_title(nbl.props.label_text)
        else:
            self.set_title("Meld")

        if isinstance(newdoc, MeldDoc):
            self.diff_handler = newdoc.next_diff_changed_signal.connect(
                self.on_next_diff_changed)
        else:
            self.diff_handler = None
        if hasattr(newdoc, 'scheduler'):
            self.scheduler.add_task(newdoc.scheduler)

    @Template.Callback()
    def after_switch_page(self, notebook, page, which):
        newdoc = notebook.get_nth_page(which)
        newdoc.on_container_switch_in_event(self.ui)
        self._update_page_action_sensitivity()

    @Template.Callback()
    def after_page_reordered(self, notebook, page, page_num):
        self._update_page_action_sensitivity()

    @Template.Callback()
    def on_page_label_changed(self, notebook, label_text):
        self.set_title(label_text)

    def on_can_undo(self, undosequence, can):
        self.actiongroup.get_action("Undo").set_sensitive(can)

    def on_can_redo(self, undosequence, can):
        self.actiongroup.get_action("Redo").set_sensitive(can)

    def on_next_diff_changed(self, doc, have_prev, have_next):
        self.actiongroup.get_action("PrevChange").set_sensitive(have_prev)
        self.actiongroup.get_action("NextChange").set_sensitive(have_next)

    def on_menu_file_new_activate(self, menuitem):
        self.append_new_comparison()

    def on_menu_save_activate(self, menuitem):
        self.current_doc().save()

    def on_menu_save_as_activate(self, menuitem):
        self.current_doc().save_as()

    def on_action_recent(self, action):
        uri = action.get_current_uri()
        if not uri:
            return
        try:
            self.append_recent(uri)
        except (IOError, ValueError):
            # FIXME: Need error handling, but no sensible display location
            pass

    def on_menu_close_activate(self, *extra):
        i = self.notebook.get_current_page()
        if i >= 0:
            page = self.notebook.get_nth_page(i)
            page.on_delete_event()

    def on_menu_undo_activate(self, *extra):
        self.current_doc().on_undo_activate()

    def on_menu_redo_activate(self, *extra):
        self.current_doc().on_redo_activate()

    def on_menu_refresh_activate(self, *extra):
        self.current_doc().on_refresh_activate()

    def on_menu_find_activate(self, *extra):
        self.current_doc().on_find_activate()

    def on_menu_find_next_activate(self, *extra):
        self.current_doc().on_find_next_activate()

    def on_menu_find_previous_activate(self, *extra):
        self.current_doc().on_find_previous_activate()

    def on_menu_replace_activate(self, *extra):
        self.current_doc().on_replace_activate()

    def on_menu_go_to_line_activate(self, *extra):
        self.current_doc().on_go_to_line_activate()

    def on_menu_copy_activate(self, *extra):
        widget = self.get_focus()
        if isinstance(widget, Gtk.Editable):
            widget.copy_clipboard()
        elif isinstance(widget, Gtk.TextView):
            widget.emit("copy-clipboard")

    def on_menu_cut_activate(self, *extra):
        widget = self.get_focus()
        if isinstance(widget, Gtk.Editable):
            widget.cut_clipboard()
        elif isinstance(widget, Gtk.TextView):
            widget.emit("cut-clipboard")

    def on_menu_paste_activate(self, *extra):
        widget = self.get_focus()
        if isinstance(widget, Gtk.Editable):
            widget.paste_clipboard()
        elif isinstance(widget, Gtk.TextView):
            widget.emit("paste-clipboard")

    def on_action_fullscreen_toggled(self, widget):
        window_state = self.get_window().get_state()
        is_full = window_state & Gdk.WindowState.FULLSCREEN
        if widget.get_active() and not is_full:
            self.fullscreen()
        elif is_full:
            self.unfullscreen()

    def on_menu_edit_down_activate(self, *args):
        self.current_doc().next_diff(Gdk.ScrollDirection.DOWN)

    def on_menu_edit_up_activate(self, *args):
        self.current_doc().next_diff(Gdk.ScrollDirection.UP)

    def on_open_external(self, *args):
        self.current_doc().open_external()

    def on_toolbar_stop_clicked(self, *args):
        doc = self.current_doc()
        if doc.scheduler.tasks_pending():
            doc.scheduler.remove_task(doc.scheduler.get_current_task())

    def page_removed(self, page, status):
        if hasattr(page, 'scheduler'):
            self.scheduler.remove_scheduler(page.scheduler)

        page_num = self.notebook.page_num(page)

        if self.notebook.get_current_page() == page_num:
            self.handle_current_doc_switch(page)

        self.notebook.remove_page(page_num)
        # Normal switch-page handlers don't get run for removing the
        # last page from a notebook.
        if not self.has_pages():
            self.on_switch_page(self.notebook, page, -1)
            self._update_page_action_sensitivity()
            # Synchronise UIManager state; this shouldn't be necessary,
            # but upstream aren't touching UIManager bugs.
            self.ui.ensure_update()
            if self.should_close:
                cancelled = self.emit(
                    'delete-event', Gdk.Event.new(Gdk.EventType.DELETE))
                if not cancelled:
                    self.emit('destroy')

    def on_page_state_changed(self, page, old_state, new_state):
        if self.should_close and old_state == ComparisonState.Closing:
            # Cancel closing if one of our tabs does
            self.should_close = False

    def on_file_changed(self, srcpage, filename):
        for page in self.notebook.get_children():
            if page != srcpage:
                page.on_file_changed(filename)

    def _append_page(self, page, icon):
        nbl = NotebookLabel(icon_name=icon, page=page)
        self.notebook.append_page(page, nbl)
        self.notebook.child_set_property(page, 'tab-expand', True)

        # Change focus to the newly created page only if the user is on a
        # DirDiff or VcView page, or if it's a new tab page. This prevents
        # cycling through X pages when X diffs are initiated.
        if isinstance(self.current_doc(), DirDiff) or \
           isinstance(self.current_doc(), VcView) or \
           isinstance(page, NewDiffTab):
            self.notebook.set_current_page(self.notebook.page_num(page))

        if hasattr(page, 'scheduler'):
            self.scheduler.add_scheduler(page.scheduler)
        if isinstance(page, MeldDoc):
            page.file_changed_signal.connect(self.on_file_changed)
            page.create_diff_signal.connect(
                lambda obj, arg, kwargs: self.append_diff(arg, **kwargs))
            page.tab_state_changed.connect(self.on_page_state_changed)
        page.close_signal.connect(self.page_removed)

        self.notebook.set_tab_reorderable(page, True)

    def append_new_comparison(self):
        doc = NewDiffTab(self)
        self._append_page(doc, "document-new")
        self.notebook.on_label_changed(doc, _("New comparison"), None)

        def diff_created_cb(doc, newdoc):
            doc.on_delete_event()
            idx = self.notebook.page_num(newdoc)
            self.notebook.set_current_page(idx)

        doc.connect("diff-created", diff_created_cb)
        return doc

    def append_dirdiff(self, gfiles, auto_compare=False):
        dirs = [d.get_path() for d in gfiles if d]
        assert len(dirs) in (1, 2, 3)
        doc = DirDiff(len(dirs))
        self._append_page(doc, "folder")
        doc.set_locations(dirs)
        if auto_compare:
            doc.scheduler.add_task(doc.auto_compare)
        return doc

    def append_filediff(
            self, gfiles, *, encodings=None, merge_output=None, meta=None):
        assert len(gfiles) in (1, 2, 3)
        doc = FileDiff(len(gfiles))
        self._append_page(doc, "text-x-generic")
        doc.set_files(gfiles, encodings)
        if merge_output is not None:
            doc.set_merge_output_file(merge_output)
        if meta is not None:
            doc.set_meta(meta)
        return doc

    def append_filemerge(self, gfiles, merge_output=None):
        if len(gfiles) != 3:
            raise ValueError(
                _("Need three files to auto-merge, got: %r") %
                [f.get_parse_name() for f in gfiles])
        doc = FileMerge(len(gfiles))
        self._append_page(doc, "text-x-generic")
        doc.set_files(gfiles)
        if merge_output is not None:
            doc.set_merge_output_file(merge_output)
        return doc

    def append_diff(self, gfiles, auto_compare=False, auto_merge=False,
                    merge_output=None, meta=None):
        have_directories = False
        have_files = False
        for f in gfiles:
            if f.query_file_type(
               Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.DIRECTORY:
                have_directories = True
            else:
                have_files = True
        if have_directories and have_files:
            raise ValueError(
                _("Cannot compare a mixture of files and directories"))
        elif have_directories:
            return self.append_dirdiff(gfiles, auto_compare)
        elif auto_merge:
            return self.append_filemerge(gfiles, merge_output=merge_output)
        else:
            return self.append_filediff(
                gfiles, merge_output=merge_output, meta=meta)

    def append_vcview(self, location, auto_compare=False):
        doc = VcView()
        self._append_page(doc, "meld-version-control")
        if isinstance(location, (list, tuple)):
            location = location[0]
        doc.set_location(location.get_path())
        if auto_compare:
            doc.scheduler.add_task(doc.auto_compare)
        return doc

    def append_recent(self, uri):
        comparison_type, gfiles = recent_comparisons.read(uri)
        comparison_method = {
            RecentType.File: self.append_filediff,
            RecentType.Folder: self.append_dirdiff,
            RecentType.Merge: self.append_filemerge,
            RecentType.VersionControl: self.append_vcview,
        }
        tab = comparison_method[comparison_type](gfiles)
        self.notebook.set_current_page(self.notebook.page_num(tab))
        recent_comparisons.add(tab)
        return tab

    def _single_file_open(self, gfile):
        doc = VcView()

        def cleanup():
            self.scheduler.remove_scheduler(doc.scheduler)
        self.scheduler.add_task(cleanup)
        self.scheduler.add_scheduler(doc.scheduler)
        path = gfile.get_path()
        doc.set_location(path)
        doc.create_diff_signal.connect(
            lambda obj, arg, kwargs: self.append_diff(arg, **kwargs))
        doc.run_diff(path)

    def open_paths(self, gfiles, auto_compare=False, auto_merge=False,
                   focus=False):
        tab = None
        if len(gfiles) == 1:
            a = gfiles[0]
            if a.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == \
                    Gio.FileType.DIRECTORY:
                tab = self.append_vcview(a, auto_compare)
            else:
                self._single_file_open(a)

        elif len(gfiles) in (2, 3):
            tab = self.append_diff(gfiles, auto_compare=auto_compare,
                                   auto_merge=auto_merge)
        if tab:
            recent_comparisons.add(tab)
            if focus:
                self.notebook.set_current_page(self.notebook.page_num(tab))

        return tab

    def current_doc(self):
        "Get the current doc or a dummy object if there is no current"
        index = self.notebook.get_current_page()
        if index >= 0:
            page = self.notebook.get_nth_page(index)
            if isinstance(page, MeldDoc):
                return page

        class DummyDoc:
            def __getattr__(self, a):
                return lambda *x: None
        return DummyDoc()
