# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from typing import cast, override
from collections import deque

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from quodlibet.library import SongLibrary
from quodlibet.util.songwrapper import SongWrapper

from . import prdb

from .config import Config
from .errors import Error
from .helpers import (
    FPContext,
    is_exportable,
    get_or_calc_fp,
)

from .dlg_base import DlgBase, Songs, TaskProgress


class Dlg(DlgBase):
    def __init__(self, config: Config, parent: Gtk.Window, library: SongLibrary):
        super().__init__("dlg_process.glade", config, parent, library)

    @override
    def _init_ui(self, parent: Gtk.Window, builder: Gtk.Builder) -> None:
        super()._init_ui(parent, builder)
        self._force_export_cb = cast(Gtk.CheckButton, builder.get_object("force"))
        self._force_export_cb.set_label("Force export QLDB to the PRDB")
        self._force_export_cb.set_tooltip_text(
            "If set, records from the Quodlibet DB will be exported to the PRDB despite"
            " the actual records timestamps. Existing records in the PRDB will be"
            " overwritten. If the flag is not set, only records with newer timestamps"
            " will be exported from the QLDB to the PRDB."
        )

    @override
    def _create_context(self) -> FPContext:
        return FPContext(self._cancellable)

    @override
    def _get_songs_to_process(self, ctx: FPContext) -> Songs:
        total_songs = len(self._library)
        self._count_songs_to_process = total_songs

        msg = f"Scanning library: {total_songs} songs..."
        self._async_log(msg)

        in_batch = 0
        total = 0

        # Find songs to process
        songs: deque[SongWrapper] = deque()
        self._force_export: bool = self._force_export_cb.get_active()

        for s in self._library.values():
            if is_exportable(s):
                songs.append(SongWrapper(s))

            in_batch += 1
            if (in_batch >= self._batch_size) or ((in_batch + total) == total_songs):
                total += in_batch
                in_batch = 0
                progress = TaskProgress()
                progress.total_processed = total
                self._async_update_progress(progress)
            if ctx.cancellable.is_cancelled():
                return deque()

        msg: str
        if len(songs) > 0:
            msg = f"To process: {len(songs)} songs\n" + "-" * 80
        else:
            msg = "Nothing to process"

        self._async_log(msg)

        return songs

    @override
    def _update_task_progress_impl(self, progress: TaskProgress) -> None:
        count_failed = len(progress.failed)
        if count_failed:
            for s in progress.failed:
                msg = f"{s}: Error: {s.error}, "
                self._log(msg)

    @override
    def _processor(self, ctx: FPContext, song: SongWrapper) -> bool | Error:
        fp = get_or_calc_fp(ctx, song)

        if isinstance(fp, Error):
            return fp

        return prdb.update_song_in_db(self._config.db_path, fp, song, self._force_export)
