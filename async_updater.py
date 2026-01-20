# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import sqlite3
import threading
import traceback

from collections import deque
from abc import ABC, abstractmethod
from typing import TypeVar, Generic, final

from gi.repository import GLib
from gi.repository.Gio import Cancellable

from quodlibet.util.songwrapper import SongWrapper
from quodlibet.util.thread import call_async_background
from quodlibet.qltk.notif import Task

from .errors import ErrorCode, Error
from .trace import print_e, print_w, print_d, print_thread_id
from .async_helpers import Songs, Queue, TaskProgress, Context, FailedSong


# Updater does not send progress messages, but the result one
class TaskResult(TaskProgress):
    pass


T = TypeVar("T", bound=Context)


class AsyncUpdater(ABC, Generic[T]):

    _ui_task_name: str

    _ui_task_descr: str

    _cancellable: Cancellable

    _lock: threading.Lock

    _queue: Queue

    _timer_id: int

    _is_running: bool

    _ui_task: Task | None

    def __init__(self, task_name, task_descr) -> None:
        super().__init__()
        self._ui_task_name = task_name
        self._ui_task_descr = task_descr
        self._lock = threading.Lock()
        self._cancellable = Cancellable()
        self._queue = deque()
        self._timer_id = 0
        self._is_running = False
        self._ui_task = None

    def stop(self) -> None:
        self._cancellable.cancel()
        if self._timer_id != 0:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0

    def append(self, songs: Songs) -> None:

        if self._cancellable.is_cancelled():
            return

        with self._lock:
            if self._ui_task is None:
                self._ui_task = Task(self._ui_task_name, self._ui_task_descr)
            for song in songs:
                self._queue.append(song)

        if (self._is_running) or (self._timer_id != 0):
            return

        self._is_running = True
        call_async_background(
            self._task_worker,
            self._cancellable,
            callback=self._on_task_finished,
            args=(self._cancellable,),
        )

    @final
    def _on_timer_event(self) -> bool:
        """Start async thread if not running and the queue is not empty"""

        self._timer_id = 0

        if self._cancellable.is_cancelled():
            return GLib.SOURCE_REMOVE

        with self._lock:
            if len(self._queue) == 0:
                if self._ui_task is not None:
                    self._ui_task.finish()
                    self._ui_task = None

                return GLib.SOURCE_REMOVE

        assert not self._is_running
        self._is_running = True

        # Start next async task
        call_async_background(
            self._task_worker,
            self._cancellable,
            callback=self._on_task_finished,
            args=(self._cancellable,),
        )

        return GLib.SOURCE_REMOVE

    @final
    def _on_task_finished(self, result: TaskResult) -> None:
        self._is_running = False

        timeout = 0

        # Lock is not needed - This is the primary Gtk thread
        q_size = len(self._queue)

        if self._cancellable.is_cancelled():
            result.error = Error(ErrorCode.CANCELLED)
        else:
            if result.error and result.error.code == ErrorCode.DB_LOCKED:
                result.error = None
                timeout = 1000  # try once a second
                print_d(f"Database is locked. Next try in {timeout} ms. Q: {q_size}")

        if q_size > 0:
            if result.error:
                for elem in self._queue:
                    r = FailedSong(elem, Error(ErrorCode.CANCELLED))
                    result.failed.append(r)
            else:
                assert self._timer_id == 0
                # Start next async task in 100 ms
                timeout = 100

        self._on_task_result_impl(result)

        if timeout != 0:
            self._timer_id = GLib.timeout_add(timeout, self._on_timer_event)
        else:
            if self._ui_task is not None:
                self._ui_task.finish()
                self._ui_task = None

    @abstractmethod
    def _create_context(self) -> T:
        pass

    def _delete_context(self, ctx: T) -> None:
        ctx.delete()

    def _on_task_result_impl(self, result: TaskResult) -> bool:
        return False

    def _processor(self, ctx: T, song: SongWrapper) -> bool | Error:
        return False

    def _task_worker(self, cancellable: Cancellable) -> TaskProgress:

        print_thread_id()

        ctx: T = self._create_context()

        result = TaskResult()

        q_size: int = 0
        q_processed: int = 0
        with self._lock:
            q_size = len(self._queue)

        while True:
            s: SongWrapper | None = None

            with self._lock:
                cur_size = len(self._queue)

                if cur_size > 0:
                    s = self._queue.popleft()

                    if self._ui_task is not None:
                        if cur_size != (q_size - q_processed):
                            q_size = cur_size + q_processed

                        q_processed += 1
                        self._ui_task.update(q_processed / q_size)

            if s is None:
                break

            try:
                res = self._processor(ctx, s)
                result.total_processed += 1
                if isinstance(res, Error):
                    result.failed.append(FailedSong(s, res))
                else:
                    assert isinstance(res, bool)
                    if res:
                        result.succeeded.append(s)
                    else:
                        result.skipped += 1

                if cancellable.is_cancelled():
                    result.error = Error(ErrorCode.CANCELLED)
                    break

            except sqlite3.Error as e:
                if (
                    e.sqlite_errorcode == sqlite3.SQLITE_LOCKED
                    or e.sqlite_errorcode == sqlite3.SQLITE_BUSY
                ):
                    with self._lock:
                        self._queue.appendleft(s)
                    result.error = Error(ErrorCode.DB_LOCKED)
                    break

                err = Error(ErrorCode.DB_ERROR, str(e))
                result.failed.append(FailedSong(s, err))
            except Exception as e:
                traceback.print_exc()
                print_e(f"Unhandled exception: {str(e)}")
                err = Error(ErrorCode.ERROR, str(e))
                result.failed.append(FailedSong(s, err))

        self._delete_context(ctx)

        return result
