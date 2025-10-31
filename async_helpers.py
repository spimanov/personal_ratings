# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from collections import deque
from collections.abc import Collection

from gi.repository.Gio import Cancellable

from quodlibet.util.songwrapper import SongWrapper

from . import attrs
from .errors import Error


class FailedSong:
    song: SongWrapper
    error: Error | None

    def __init__(self, song: SongWrapper, error: Error | None = None) -> None:
        self.song = song
        self.error = error

    def __str__(self) -> str:
        return self.song[attrs.BASENAME]


type Songs = Collection[SongWrapper]

type Queue = deque[SongWrapper]

type SucceededSongs = list[SongWrapper]

type FailedSongs = list[FailedSong]


class TaskProgress:
    total_processed: int
    """ Count of totally processed (succeeded, failed, skipped) songs so far, since the
    task start """

    succeeded: SucceededSongs
    """ List of successfully processed songs. This is a partial result of the task, last
    iteration result. """

    failed: FailedSongs
    """ List of songs failed to process. Last iteration result. """

    skipped: int
    """ Count of songs that were successfully processed, but no updates were performed
    (e.g. update is not needed, because PRDB already contains the same song stats).
    Last iteration result.
    """

    error: Error | None
    """ Overall task status: success or an error"""

    def __init__(self) -> None:
        self.total_processed = 0
        self.succeeded = []
        self.failed = []
        self.skipped = 0
        self.error = None


class TaskResult:
    total_processed: int
    """ Count of totally processed (succeeded, failed, skipped) songs so far, since the
    task start """

    total_succeeded: int
    """ Count of successfully processed songs """

    total_failed: int
    """ Count of unprocessed songs (last iteration) """

    total_skipped: int
    """ Songs that were skipped (e.g. updates are not needed, PRDB contains the same
    stats) """

    error: Error | None
    """ Overall task status: success or an error"""

    def __init__(self) -> None:
        self.total_processed = 0
        self.total_succeeded = 0
        self.total_failed = 0
        self.total_skipped = 0
        self.error = None

    def add(self, progress: TaskProgress) -> None:
        ls = len(progress.succeeded)
        lf = len(progress.failed)
        self.total_succeeded += ls
        self.total_failed += lf
        self.total_skipped += progress.skipped
        self.total_processed += ls + lf + progress.skipped


class Context:
    """Thread executable context.
    Used to initialize and keep some thread-related variables in derived classes.
    """

    cancellable: Cancellable

    def __init__(self, cancellable: Cancellable) -> None:
        self.cancellable = cancellable

    # @virtual
    def delete(self) -> None:
        """Is called just before context releasing. The working thread will be finished
        after this call"""
        pass
