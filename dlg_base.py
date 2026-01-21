# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import traceback
import sqlite3
import time

from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Generic, TypeVar, cast, final

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk
from gi.repository.Gio import Cancellable

from quodlibet.library import SongLibrary
from quodlibet.util.songwrapper import SongWrapper
from quodlibet.util.thread import call_async

from .async_helpers import Context, TaskProgress, TaskResult, FailedSong
from .config import Config
from .errors import Error, ErrorCode
from .trace import print_e, print_d

type Songs = deque[SongWrapper]

T = TypeVar("T", bound=Context)

DEF_BATCH_SIZE = 25


class DlgBase(ABC, Generic[T]):
    def __init__(
        self,
        glade_file: str,
        config: Config,
        parent: Gtk.Window,
        library: SongLibrary,
        batch_size: int = DEF_BATCH_SIZE,
    ):
        self._config = config
        self._parent = parent
        self._library = library
        self._batch_size = batch_size
        self._is_running = False
        self._cancellable = Cancellable()
        self._count_songs_to_process = 0

        self.builder = builder = Gtk.Builder()
        script_directory = Path(__file__).resolve().parent
        builder.add_from_file(str(script_directory / glade_file))

        self._init_ui(parent, builder)

        builder.connect_signals(self)

    def _init_ui(self, parent: Gtk.Window, builder: Gtk.Builder) -> None:
        self._dlg = cast(Gtk.Dialog, builder.get_object("main"))
        self._dlg.set_transient_for(parent)
        self._dlg.set_modal(True)

        self._log_tv = cast(Gtk.TextView, builder.get_object("log_tv"))
        self._force_regen = cast(Gtk.CheckButton, builder.get_object("force_regen"))
        self._progress = cast(Gtk.ProgressBar, builder.get_object("progress"))
        self._start_btn = cast(Gtk.Button, builder.get_object("start_btn"))
        self._stop_btn = cast(Gtk.Button, builder.get_object("stop_btn"))
        self._close_btn = cast(Gtk.Button, builder.get_object("close_btn"))

        self._stop_btn.set_sensitive(False)
        self._progress.set_fraction(0.0)
        self._progress.set_text("")

    def run(self):
        self._dlg.run()

    def destroy(self):
        self._dlg.destroy()

    def _on_delete_event(self, dialog: Gtk.Widget, event: Gdk.Event) -> bool:
        # Return True to prevent the dialog from destroying, False to allow it
        # User confirmation is shown in the "response" handler, it comes first
        return self._is_running

    def _on_dlg_response(self, dialog, response):
        if (
            response == Gtk.ResponseType.DELETE_EVENT
            or response == Gtk.ResponseType.CLOSE
        ):
            # if cancelling is already in progress
            if self._cancellable.is_cancelled():
                dialog.stop_emission_by_name("response")
                return

            if self._is_running:
                if not self._confirm_to_close():
                    dialog.stop_emission_by_name("response")
                    return
                self._stop()

        self._dlg.hide()
        self._dlg.disconnect_by_func(self._on_dlg_response)
        self._dlg.destroy()

    def _close_btn_clicked_cb(self, btn: Gtk.Button) -> None:
        assert not self._is_running
        self._dlg.destroy()

    def _confirm_to_close(self) -> bool:
        dialog = Gtk.MessageDialog(
            parent=self._dlg,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Do you want to cancel the processing?",
        )
        dialog.format_secondary_text("This action cannot be undone.")

        response = dialog.run()
        result = response == Gtk.ResponseType.YES
        dialog.destroy()

        return result

    def _start_btn_clicked_cb(self, btn: Gtk.Button) -> None:
        # Clear the log
        buffer = self._log_tv.get_buffer()
        buffer.set_text("", -1)

        # Revert to automatic percentage display for other values
        self._progress.set_text(None)
        self._progress.set_fraction(0.0)

        self._start_btn.set_sensitive(False)
        self._close_btn.set_sensitive(False)
        self._stop_btn.set_sensitive(True)
        self._cancellable.reset()
        self._is_running = True
        self._time_start = time.time()

        call_async(
            self._task_worker,
            self._cancellable,
            callback=self._on_task_finished,
            args=(self._cancellable,),
        )

    def _stop_btn_clicked_cb(self, btn: Gtk.Button) -> None:
        self._stop_btn.set_sensitive(False)
        if self._confirm_to_close():
            self._stop()
        else:
            self._stop_btn.set_sensitive(True)

    def _stop(self) -> None:
        if self._is_running:
            self._cancellable.cancel()

    def _log(self, msg: str) -> bool:
        buff = self._log_tv.get_buffer()
        iter = buff.get_end_iter()
        buff.insert(iter, msg + "\n")
        mark = buff.create_mark("end_mark", buff.get_end_iter(), True)
        self._log_tv.scroll_to_mark(mark, 0.0, False, 0.0, 1.0)

        return GLib.SOURCE_REMOVE

    def _get_songs_to_process(self, ctx: T) -> Songs:
        return deque()

    @abstractmethod
    def _create_context(self) -> T:
        pass

    def _delete_context(self, ctx: T) -> None:
        ctx.delete()

    @final
    def _update_task_progress(self, progress: TaskProgress) -> bool:
        """Gtk handler of the idle_add method call"""

        if self._count_songs_to_process != 0:
            v = progress.total_processed / self._count_songs_to_process
        else:
            v = 0.0

        if 0.99 < v < 1.0:
            self._progress.set_text("99%")
        elif v >= 1.0:
            self._progress.set_text("100%")

        self._progress.set_fraction(v)

        self._update_task_progress_impl(progress)

        return GLib.SOURCE_REMOVE

    def _update_task_progress_impl(self, progress: TaskProgress) -> None:
        """Handler to be overwritten in derived classes"""
        if len(progress.succeeded):
            self._library.changed(progress.succeeded)

        count_failed = len(progress.failed)
        if count_failed:
            for s in progress.failed:
                msg = f"{s}: Error: {s.error}, "
                self._log(msg)

    @final
    def _on_task_finished(self, result: TaskResult) -> bool:
        """Gtk handler of the idle_add method call"""
        self._stop_btn.set_sensitive(False)
        self._start_btn.set_sensitive(True)
        self._close_btn.set_sensitive(True)
        self._is_running = False

        duration = time.time() - self._time_start
        self._on_task_finished_impl(duration, result)

        return GLib.SOURCE_REMOVE

    def _on_task_finished_impl(self, duration: float, result: TaskResult) -> None:
        """Handler to be overwritten in derived classes"""
        msg = (
            f"Done: processed: {result.total_succeeded}, unprocessed:"
            f" {result.total_failed}, skipped: {result.total_skipped}, duration:"
            f" {duration:.2f} sec\n"
        )

        if result.error is not None:
            msg = msg + f"\nError: {result.error.code.name}"
            if result.error.msg is not None:
                msg = msg + f": {result.error.msg}"

        self._log(msg)

    def _processor(self, ctx: T, song: SongWrapper) -> bool | Error:
        return False

    def _async_event(self, func: Callable, *args) -> None:
        assert func is not None
        GLib.idle_add(func, *args, priority=GLib.PRIORITY_DEFAULT)
        time.sleep(0.01)

    def _async_log(self, msg: str) -> None:
        self._async_event(self._log, msg)

    def _async_update_progress(self, progress: TaskProgress) -> None:
        self._async_event(self._update_task_progress, progress)

    def _task_worker(self, cancellable: Cancellable) -> TaskResult:

        ctx: T = self._create_context()

        songs = self._get_songs_to_process(ctx)
        self._count_songs_to_process = len(songs)

        result = TaskResult()
        progress = TaskProgress()
        count_batch = 0

        while len(songs):
            s = songs.popleft()

            try:
                res = self._processor(ctx, s)

            except sqlite3.Error as e:
                if (
                    e.sqlite_errorcode == sqlite3.SQLITE_LOCKED
                    or e.sqlite_errorcode == sqlite3.SQLITE_BUSY
                ):
                    songs.appendleft(s)
                    progress.error = Error(ErrorCode.DB_LOCKED)
                    self._async_update_progress(progress)
                    progress = TaskProgress()
                    count_batch = 0
                    time.sleep(1)
                    continue

                res = Error(ErrorCode.DB_ERROR, str(e))
                # send notification about the error  immediately
                count_batch = self._batch_size

            except Exception as e:
                traceback.print_exc()
                print_e(f"Exc: {str(e)}")
                res = Error(ErrorCode.ERROR, str(e))
                # send notification about the error  immediately
                count_batch = self._batch_size

            if isinstance(res, Error):
                progress.failed.append(FailedSong(s, res))
            else:
                assert isinstance(res, bool)
                if res:
                    progress.succeeded.append(s)
                else:
                    progress.skipped += 1

            count_batch += 1

            if cancellable.is_cancelled():
                result.error = Error(ErrorCode.CANCELLED)
                progress.error = Error(ErrorCode.CANCELLED)
                for s in songs:
                    progress.failed.append(FailedSong(s, Error(ErrorCode.CANCELLED)))
                    count_batch += 1
                break

            if count_batch >= self._batch_size:
                count_batch = 0
                result.add(progress)
                progress.total_processed = result.total_processed

                self._async_update_progress(progress)
                progress = TaskProgress()

        if count_batch != 0:
            result.add(progress)
            self._async_update_progress(progress)
            progress = TaskProgress()
            count_batch = 0

        self._delete_context(ctx)

        # call_async does not call callback in case if cancelled is set
        # Force call it.
        if cancellable.is_cancelled():
            self._async_event(self._on_task_finished, result)

        return result
