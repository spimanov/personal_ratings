# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.


import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from gi.repository.Gio import Cancellable

from typing import override
from pathlib import Path

from quodlibet.library import SongLibrary
from quodlibet.util.songwrapper import SongWrapper

from . import attrs, prdb

from .config import Config
from .dlg_base import DlgBase, TaskProgress, TaskResult
from .errors import Error, ErrorCode
from .helpers import FPContext, is_updatable, rating_to_float, are_equal
from .prdb import DBRecord, DBRecordBase


class CancelledError(Exception):
    def __init__(self) -> None:
        super().__init__("Cancelled")


def extract_rec(rec: DBRecord, db_records: list[DBRecord]) -> DBRecord | None:
    index = 0
    num = len(db_records)
    while index < num:
        r = db_records[index]
        if r.fp == rec.fp:
            return db_records.pop(index)
        index += 1

    return None


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
        self, inl: list[DBRecord], inr: list[DBRecord], cancellable: Cancellable
    ) -> tuple[list[DBRecord], list[DBRecordBase], list[DBRecord], list[DBRecordBase]]:

        result = TaskResult()
        progress = TaskProgress()
        count_batch = 0

        def _send_update(predicate: bool):
            nonlocal count_batch
            nonlocal progress
            if predicate:
                count_batch = 0
                progress.total_processed = result.total_processed

                self._async_update_progress(progress)
                progress = TaskProgress()

        def _step(step: int = 1):
            nonlocal count_batch
            nonlocal result

            count_batch += step
            result.total_succeeded += step
            result.total_processed += step

            if cancellable.is_cancelled():
                raise CancelledError()

            _send_update(count_batch > self._batch_size)

        # ================================================================================

        to_addl: list[DBRecord] = []
        to_updl: list[DBRecordBase] = []

        to_addr: list[DBRecord] = []
        to_updr: list[DBRecordBase] = []

        self._count_songs_to_process = len(inl) + len(inr)

        # ================================================================================
        # Step 1, iterate over the left (local)
        while len(inl):

            if cancellable.is_cancelled():
                raise CancelledError()

            recl = inl.pop(0)

            recr = extract_rec(recl, inr)

            _step(2)

            if recr is None:
                to_addr.append(recl)
            else:
                if are_equal(recl.rating, recr.rating):
                    continue
                l_ts = recl.timestamp()
                r_ts = recr.timestamp()
                if l_ts < r_ts:
                    recl.rating = recr.rating
                    recl.updated_at = r_ts
                    to_updl.append(recl)
                else:
                    recr.rating = recl.rating
                    recr.updated_at = l_ts
                    to_updr.append(recr)

        # ================================================================================
        # Step 2, iterate over the remainings of the right (remote)
        while len(inr):

            if cancellable.is_cancelled():
                raise CancelledError()

            recr = inr.pop(0)
            to_addl.append(recr)
            _step(1)

        self._progress.set_fraction(1.0)
        self._progress.set_text(None)

        return (to_addl, to_updl, to_addr, to_updr)

    def _update_local(self, rec: DBRecordBase) -> list[SongWrapper] | None:
        # Update record in the local DB unconditionally
        prdb.force_song_update(self._config.db_path, rec)

        result: list[SongWrapper] = []
        rating = rating_to_float(rec.rating)

        for s in self._library.values():
            if (not is_updatable(s)) or attrs.FP_ID not in s:
                continue

            fp_id = s(attrs.FP_ID)
            if fp_id != rec.fp_id:
                continue

            if are_equal(s(attrs.RATING), rating):
                continue

            song = SongWrapper(s)
            song[attrs.RATING] = rating
            result.append(song)

        return result

    def _task_worker(self, cancellable: Cancellable) -> TaskResult:

        result = TaskResult()
        progress = TaskProgress()
        count_batch = 0

        def _send_update(predicate: bool):
            nonlocal count_batch
            nonlocal progress
            if predicate:
                count_batch = 0
                progress.total_processed = result.total_processed

                self._async_update_progress(progress)
                progress = TaskProgress()

        def _step():
            nonlocal count_batch
            nonlocal result

            count_batch += 1
            result.total_succeeded += 1
            result.total_processed += 1

            if cancellable.is_cancelled():
                raise CancelledError()

            _send_update(count_batch > self._batch_size)

        try:

            self._async_log("Loading local PRDB...")
            loc = prdb.get_songs(self._config.db_path)
            self._async_log(f"Local PRDB contains {len(loc)} records")

            if cancellable.is_cancelled():
                raise CancelledError()

            self._async_log("Loading external PRDB...")
            ext = prdb.get_songs(self._config.ext_db_path)
            self._async_log(f"External PRDB contains {len(ext)} records")

            if cancellable.is_cancelled():
                raise CancelledError()


            self._async_log("Comparing databases...")
            to_addl, to_updl, to_addr, to_updr = self._get_diff(loc, ext, cancellable)

            self._async_log(
                f"to import <= add: {len(to_addl)}, upd: {len(to_updl)} records"
            )
            self._async_log(
                f"to export => add: {len(to_addr)}, upd: {len(to_updr)} records"
            )

            self._count_songs_to_process = (
                len(to_addl) + len(to_updl) + len(to_addr) + len(to_updr)
            )

            # ===========================================================================
            # Update existing records in both local dbs: PRDB and QLDB
            for rec in to_updl:
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
                    raise CancelledError()

                _send_update(count_batch > self._batch_size)

            _send_update(count_batch != 0)

            # ===========================================================================
            # Add new records to the local PRDB
            for rec in to_addl:
                prdb.add_song(self._config.db_path, rec.basename, rec.rating, rec.fp)
                _step()

            _send_update(count_batch != 0)

            # ===========================================================================
            # Update records in the external PRDB
            for rec in to_updr:
                prdb.force_song_update(self._config.ext_db_path, rec)
                _step()

            _send_update(count_batch != 0)

            # ===========================================================================
            # Add new records to the external PRDB
            for rec in to_addr:
                prdb.add_song(self._config.ext_db_path, rec.basename, rec.rating, rec.fp)
                _step()

            _send_update(count_batch != 0)

        except CancelledError:
            result.error = Error(ErrorCode.CANCELLED)
            progress.error = Error(ErrorCode.CANCELLED)
            count_batch = 1
        except Exception as e:
            err = Error(ErrorCode.ERROR, str(e))
            result.error = err
            progress.error = err
            count_batch = 1

        _send_update(count_batch != 0)

        # call_async does not call callback in case if cancelled is set
        # Force call it.
        if cancellable.is_cancelled():
            self._async_event(self._on_task_finished, result)

        return result
