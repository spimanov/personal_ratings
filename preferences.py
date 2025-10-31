# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from typing import cast

from pathlib import Path

from quodlibet import qltk
from quodlibet import app

from .config import Config

from .trace import print_d


class Preferences:
    def __init__(self, config: Config):
        self._config = config

    def create(self, parent: Gtk.Box) -> Gtk.Widget:
        self.parent = parent
        self.builder = builder = Gtk.Builder()
        script_directory = Path(__file__).resolve().parent
        builder.add_from_file(str(script_directory / "preferences.glade"))
        prdb_box = cast(Gtk.Widget, builder.get_object("main_box"))

        self.use_custom_db_path = ccb = cast(
            Gtk.CheckButton, builder.get_object("use_custom_db_path")
        )
        self.custom_db_path = cast(Gtk.Entry, builder.get_object("custom_db_path"))
        self.custom_db_path_btn = cast(
            Gtk.Button, builder.get_object("custom_db_path_btn")
        )

        use_custom = self._config.use_custom_db_path
        ccb.set_active(use_custom)
        self.custom_db_path.set_sensitive(use_custom)
        self.custom_db_path_btn.set_sensitive(use_custom)
        self.custom_db_path.set_text(self._config.db_path)

        self.use_ext_db = ccb = cast(Gtk.CheckButton, builder.get_object("use_ext_db"))
        self.ext_db_path = cast(Gtk.Entry, builder.get_object("ext_db_path"))
        self.ext_db_path_btn = cast(Gtk.Button, builder.get_object("ext_db_path_btn"))
        self.sync_with_ext_btn = cast(Gtk.Button, builder.get_object("sync_with_ext_btn"))
        state = self._config.sync_with_ext
        ccb.set_active(state)
        self.ext_db_path.set_text(self._config.ext_db_path)
        self.ext_db_path.set_sensitive(state)
        self.ext_db_path_btn.set_sensitive(state)
        self.sync_with_ext_btn.set_sensitive(state)

        builder.connect_signals(self)

        return prdb_box

    def use_custom_db_path_toggled_cb(self, chbox: Gtk.CheckButton) -> None:
        use_custom = chbox.get_active()
        self.custom_db_path.set_sensitive(use_custom)
        self.custom_db_path_btn.set_sensitive(use_custom)
        self._config.use_custom_db_path = use_custom
        if use_custom:
            self._config.db_path = self._config.custom_db_path
        else:
            self._config.db_path = self._config.default_db_path

        self.set_custom_db_path(self._config.db_path)

    def custom_db_path_btn_clicked_cb(self, btn: Gtk.Button) -> None:
        path = Path(self.custom_db_path.get_text())
        if path.exists():
            if path.is_dir():
                path = path / "personal.db"

        new_path = self.open_db_dialog("PRDB file location", path)
        if new_path is not None:
            self._config.custom_db_path = new_path
            self._config.db_path = new_path
            self.set_custom_db_path(new_path)

    def custom_db_path_changed_cb(self, entry) -> None:
        new_path = entry.get_text()
        self._config.custom_db_path = new_path
        self._config.db_path = new_path

    def set_custom_db_path(self, text) -> None:
        self.custom_db_path.handler_block_by_func(self.custom_db_path_changed_cb)
        self.custom_db_path.set_text(text)
        self.custom_db_path.handler_unblock_by_func(self.custom_db_path_changed_cb)

    def use_ext_db_toggled_cb(self, chbox: Gtk.CheckButton) -> None:
        state = chbox.get_active()
        self.ext_db_path.set_sensitive(state)
        self.ext_db_path_btn.set_sensitive(state)
        self.sync_with_ext_btn.set_sensitive(state)
        self._config.sync_with_ext = state

    def ext_db_path_btn_clicked_cb(self, btn: Gtk.Button) -> None:
        path = Path(self.ext_db_path.get_text())
        new_path = self.open_db_dialog("External PRDB file location", path)
        if new_path is not None:
            self._config.ext_db_path = new_path
            self.set_ext_db_path(new_path)

    def ext_db_path_changed_cb(self, entry) -> None:
        text = entry.get_text()
        self._config.ext_db_path = text

    def set_ext_db_path(self, text) -> None:
        self.ext_db_path.handler_block_by_func(self.ext_db_path_changed_cb)
        self.ext_db_path.set_text(text)
        self.ext_db_path.handler_unblock_by_func(self.ext_db_path_changed_cb)

    def open_db_dialog(self, title: str, path: Path) -> str | None:
        top_parent = cast(Gtk.Window, qltk.get_top_parent(self.parent))
        dialog = Gtk.FileChooserDialog(
            title=title, action=Gtk.FileChooserAction.SAVE, transient_for=top_parent
        )

        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE,
            Gtk.ResponseType.OK,
        )

        dialog.set_current_folder(str(path.parent))
        dialog.set_current_name(str(path))

        filter_any = Gtk.FileFilter()
        filter_any.set_name("Any files")
        filter_any.add_pattern("*")
        dialog.add_filter(filter_any)

        filter_text = Gtk.FileFilter()
        filter_text.set_name("Db files")
        filter_text.add_mime_type("application/x-sqlite3")
        dialog.add_filter(filter_text)
        response = dialog.run()

        result = None
        if response == Gtk.ResponseType.OK:
            result = dialog.get_filename()
        dialog.destroy()

        return result

    def gen_fps_btn_clicked_cb(self, btn: Gtk.Button) -> None:
        from .dlg_gen_fps import Dlg

        top_parent = cast(Gtk.Window, qltk.get_top_parent(self.parent))
        dlg = Dlg(self._config, top_parent, app.library)
        dlg.run()
        dlg.destroy()

    def process_dup_btn_clicked_cb(self, btn: Gtk.Button) -> None:
        from .dlg_proc_dups import Dlg

        top_parent = cast(Gtk.Window, qltk.get_top_parent(self.parent))
        dlg = Dlg(self._config, top_parent, app.library)
        dlg.run()
        dlg.destroy()

    def ql_to_pr_btn_clicked_cb(self, btn: Gtk.Button) -> None:
        from .dlg_export_to_prdb import Dlg

        top_parent = cast(Gtk.Window, qltk.get_top_parent(self.parent))
        dlg = Dlg(self._config, top_parent, app.library)
        dlg.run()
        dlg.destroy()

    def pr_to_ql_btn_clicked_cb(self, btn: Gtk.Button) -> None:
        from .dlg_import_from_prdb import Dlg

        top_parent = cast(Gtk.Window, qltk.get_top_parent(self.parent))
        dlg = Dlg(self._config, top_parent, app.library)
        dlg.run()
        dlg.destroy()

    def sync_with_ext_btn_clicked_cb(self, btn: Gtk.Button) -> None:
        from .dlg_sync_with_ext import Dlg

        top_parent = cast(Gtk.Window, qltk.get_top_parent(self.parent))
        dlg = Dlg(self._config, top_parent, app.library)
        dlg.run()
        dlg.destroy()
