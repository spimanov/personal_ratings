# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from typing import override
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from gi.repository.Gio import Cancellable

from quodlibet.library import SongLibrary
from quodlibet.util.songwrapper import SongWrapper

from . import attrs
from . import prdb

from .config import Config
from .dlg_base import DlgBase, TaskProgress, TaskResult
from .errors import Error, ErrorCode
from .helpers import FPContext, is_updatable, Record, update_song_stats


class Dlg(DlgBase):
    def __init__(self, config: Config, parent: Gtk.Window, library: SongLibrary):
        super().__init__("dlg_proc_dups.glade", config, parent, library)

    @override
    def _init_ui(self, parent: Gtk.Window, builder: Gtk.Builder) -> None:
        super()._init_ui(parent, builder)

        if not Path(self._config.ext_db_path).is_file():
            # Create new external database if not exists
            prdb.create_db(self._config.ext_db_path)

    @override
    def _create_context(self) -> FPContext:
        return FPContext(self._cancellable)

    @override
    def _update_task_progress_impl(self, progress: TaskProgress) -> None:
        if len(progress.succeeded):
            self._library.changed(progress.succeeded)

    def _get_diff(
        self, left: list[Record], right: list[Record]
    ) -> tuple[list[Record], list[Record]]:
        # Convert PRDB lists to sets, because PRDB records have unique fingerprints
        ls = set(left)
        rs = set(right)

        # Filter 1: Remove equal elements from both sets
        to_l1 = list(rs - ls)
        to_r1 = list(ls - rs)

        # Filter 2: Select only new and younger records from both sides
        to_l2: list[Record] = []
        to_r2: list[Record] = []

        for rl in to_l1:
            rr: Record | None = None
            rr_idx = 0
            for r in to_r1:
                if rl.fp == r.fp:
                    rr = r
                    break
                rr_idx += 1

            if rr is None:
                to_l2.append(rl)
            elif rl.is_younger(rr):
                to_l2.append(rl)
                del to_r1[rr_idx]
            else:
                to_r2.append(rr)
                del to_r1[rr_idx]

        to_r2.extend(to_r1)

        return (to_l2, to_r2)

    def _update_local(self, rec: Record) -> list[SongWrapper] | None:
        if not prdb.update_rec(self._config.db_path, rec):
            return None

        result: list[SongWrapper] = []

        for s in self._library.values():
            if (not is_updatable(s)) or attrs.FINGERPRINT not in s:
                continue

            song_fp = s(attrs.FINGERPRINT)
            if song_fp != rec.fp:
                continue

            song = SongWrapper(s)
            if update_song_stats(song, rec):
                result.append(song)

        return result

    def _task_worker(self, cancellable: Cancellable) -> TaskResult:

        result = TaskResult()

        # Convert PRDB lists to sets, because PRDB records have unique fingerprints

        self._async_log("Scanning local PRDB...")
        loc = prdb.get_songs(self._config.db_path)
        self._async_log(f"Local PRDB contains {len(loc)} records")

        if cancellable.is_cancelled():
            result.error = Error(ErrorCode.CANCELLED)
            return result

        self._async_log("Scanning external PRDB...")
        ext = prdb.get_songs(self._config.ext_db_path)
        self._async_log(f"External PRDB contains {len(ext)} records")

        if cancellable.is_cancelled():
            result.error = Error(ErrorCode.CANCELLED)
            return result

        to_loc, to_ext = self._get_diff(loc, ext)

        self._async_log(f"to import <= {len(to_loc)} records")
        self._async_log(f"to export => {len(to_ext)} records")

        self._count_songs_to_process = len(to_loc) + len(to_ext)

        progress = TaskProgress()
        count_batch = 0

        try:
            # Process the right list (from external to local)
            for rec in to_loc:
                songs = self._update_local(rec)
                if songs is None:
                    progress.skipped += 1
                    result.total_skipped += 1
                else:
                    progress.succeeded.extend(songs)
                    result.total_succeeded += 1

                count_batch += 1
                result.total_processed += 1

                if cancellable.is_cancelled():
                    result.error = Error(ErrorCode.CANCELLED)
                    progress.error = Error(ErrorCode.CANCELLED)
                    break

                if count_batch > self._batch_size:
                    count_batch = 0
                    progress.total_processed = result.total_processed

                    self._async_update_progress(progress)
                    progress = TaskProgress()

            if count_batch != 0:
                count_batch = 0
                progress.total_processed = result.total_processed
                self._async_update_progress(progress)
                progress = TaskProgress()

            # Process the left list (from local to external)
            for rec in to_ext:
                prdb.update_rec(self._config.ext_db_path, rec)
                result.total_succeeded += 1

                count_batch += 1
                result.total_processed += 1

                if cancellable.is_cancelled():
                    result.error = Error(ErrorCode.CANCELLED)
                    progress.error = Error(ErrorCode.CANCELLED)
                    break

                if count_batch > self._batch_size:
                    count_batch = 0
                    progress.total_processed = result.total_processed

                    self._async_update_progress(progress)
                    progress = TaskProgress()

        except Exception as e:
            err = Error(ErrorCode.ERROR, str(e))
            result.error = err
            progress.error = err

        if count_batch != 0:
            progress.total_processed = result.total_processed
            self._async_update_progress(progress)
            progress = TaskProgress()

        # call_async does not call callback in case if cancelled is set
        # Force call it.
        if cancellable.is_cancelled():
            self._async_event(self._on_task_finished, result)

        return result
