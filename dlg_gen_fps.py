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

from . import attrs

from .config import Config
from .errors import Error
from .helpers import (
    FPContext,
    is_updatable,
    calc_fp,
)

from .dlg_base import DlgBase, Songs, TaskProgress


class Dlg(DlgBase):
    def __init__(self, config: Config, parent: Gtk.Window, library: SongLibrary):
        super().__init__("dlg_process.glade", config, parent, library, 100)

    @override
    def _init_ui(self, parent: Gtk.Window, builder: Gtk.Builder) -> None:
        super()._init_ui(parent, builder)
        self._force_regen = cast(Gtk.CheckButton, builder.get_object("force"))
        self._force_regen.set_label("Force regenerate all fingerprints")
        self._force_regen.set_tooltip_text(
            "If set, fingerprints will be re-generated (overwritten) for all songs in"
            " the QL DB. If the flag is not set, fingeprints will be generated only for"
            " songs that do not have them."
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
        all: bool = self._force_regen.get_active()

        for s in self._library.values():
            if is_updatable(s):
                if all or (attrs.FINGERPRINT not in s):
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
        fp = calc_fp(ctx, song)
        if isinstance(fp, Error):
            return fp

        return True
