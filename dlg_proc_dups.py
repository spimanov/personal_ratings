# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import time

from typing import override
from collections import deque

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from gi.repository.Gio import Cancellable

from quodlibet.library import SongLibrary
from quodlibet.util.songwrapper import SongWrapper

from . import attrs

from .config import Config
from .errors import Error, ErrorCode
from .async_updater import Context

from .dlg_base import DlgBase, Songs, TaskProgress, TaskResult
from .helpers import (
    is_updatable,
)


class Dlg(DlgBase[Context]):
    def __init__(self, config: Config, parent: Gtk.Window, library: SongLibrary):
        super().__init__("dlg_proc_dups.glade", config, parent, library, 100)

    @override
    def _create_context(self) -> Context:
        return Context(self._cancellable)

    @override
    def _get_songs_to_process(self, ctx: Context) -> Songs:

        total_songs = len(self._library)
        self._count_songs_to_process = total_songs

        msg = f"Scanning library: {total_songs} songs..."
        self._async_log(msg)

        in_batch = 0
        total = 0

        # Find songs to process
        songs: deque[SongWrapper] = deque()

        for s in self._library.values():
            if is_updatable(s):
                if attrs.FP_ID in s:
                    songs.append(SongWrapper(s))
                else:
                    msg = f"{s(attrs.FILENAME)} does not have fingerprint, skipped"
                    self._async_log(msg)
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
        self._progress.set_text(None)

        return songs

    @override
    def _update_task_progress_impl(self, progress: TaskProgress) -> None:
        count_succeeded = len(progress.succeeded)
        if count_succeeded == 0:
            return

        # the Processed list contains duplicated songs
        for s in progress.succeeded:
            self._log(f"duplicate: {s(attrs.FILENAME)}")
        self._log("-" * 80)

    @override
    def _on_task_finished_impl(self, duration: float, result: TaskResult) -> None:
        duration = time.time() - self._time_start
        msg = (
            f"Processing done\nprocessed: {result.total_processed} songs,"
            f" duplicates: {result.total_skipped},"
            f" duration: {duration:.2f} sec"
        )
        if result.error is not None:
            msg = msg + f"\nError: {result.error.code.name}"
            if result.error.msg is not None:
                msg = msg + f": {result.error.msg}"

        self._log(msg)

    def _task_worker(self, cancellable: Cancellable) -> TaskResult:

        ctx = self._create_context()
        result = TaskResult()
        progress = TaskProgress()
        in_batch = 0

        songs = self._get_songs_to_process(ctx)
        self._count_songs_to_process = len(songs)

        while len(songs):
            song = songs.popleft()

            try:
                fp_id = song(attrs.FP_ID)

                result.total_processed += 1
                in_batch += 1
                progress.total_processed = result.total_processed

                dups = list(filter(lambda s: s(attrs.FP_ID) == fp_id, songs))
                if len(dups) > 0:
                    songs = deque(filter(lambda s: s(attrs.FP_ID) != fp_id, songs))
                    progress.succeeded = [song, *dups]
                    result.total_skipped += len(dups)
                    result.total_processed += len(dups)
                    self._async_update_progress(progress)
                    progress = TaskProgress()
                    in_batch = 0
                elif in_batch >= self._batch_size:
                    self._async_update_progress(progress)
                    progress = TaskProgress()
                    in_batch = 0

                if cancellable.is_cancelled():
                    result.error = Error(ErrorCode.CANCELLED)
                    break
            except Exception as e:
                result.error = Error(ErrorCode.ERROR, str(e))
                break

        if in_batch != 0:
            progress.total_processed = result.total_processed
            self._async_update_progress(progress)

        self._delete_context(ctx)

        # call_async does not call callback in case if cancelled is set
        # Force call it.
        if cancellable.is_cancelled():
            self._async_event(self._on_task_finished, result)

        return result
