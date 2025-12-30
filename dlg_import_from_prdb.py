# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import gi

gi.require_version("Gtk", "3.0")
from collections import deque
from typing import cast, override

from gi.repository import Gtk
from quodlibet.library import SongLibrary
from quodlibet.util.songwrapper import SongWrapper

from . import attrs, prdb
from .config import Config
from .dlg_base import DlgBase, Songs, TaskProgress
from .errors import Error, ErrorCode
from .helpers import FPContext, is_updatable, rating_to_float, rating_to_int


class Dlg(DlgBase):
    def __init__(self, config: Config, parent: Gtk.Window, library: SongLibrary):
        super().__init__("dlg_process.glade", config, parent, library)

    @override
    def _init_ui(self, parent: Gtk.Window, builder: Gtk.Builder) -> None:
        super()._init_ui(parent, builder)
        self._force_import_cb = cast(Gtk.CheckButton, builder.get_object("force"))
        self._force_import_cb.set_label("Force import from PRDB to QLDB")
        self._force_import_cb.set_tooltip_text(
            "If set, records in the Quodlibet DB will be overwritten by records from"
            " the PRDB despite the actual records timestamps."
            " If the flag is not set, only records with newer timestamps"
            " will be updated. In any case, only those records that exist in both DBs"
            " are updated."
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
        self._force_import: bool = self._force_import_cb.get_active()

        for s in self._library.values():
            if is_updatable(s):
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
    def _processor(self, ctx: FPContext, song: SongWrapper) -> bool | Error:
        # Ensure the fingerprint of the song
        if attrs.FP_ID not in song:
            return Error(ErrorCode.FINGERPRINT_ERROR)

        fp_id = song[attrs.FP_ID]
        rating = rating_to_int(song(attrs.RATING))
        ts = 0
        if "~#laststarted" in song:
            ts = song("~#laststarted")

        rec = prdb.get_song(self._config.db_path, fp_id)

        rec_ts = rec.timestamp()

        if self._force_import or (ts < rec_ts):
            if rating != rec.rating:
                if rating != rec.rating:
                    song[attrs.RATING] = rating_to_float(rec.rating)
                song["~#laststarted"] = rec_ts
                return True

        return False
