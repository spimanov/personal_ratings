# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from pathlib import Path
from typing import override

from quodlibet import app
from quodlibet.library.song import SongLibrary
from quodlibet.util.songwrapper import SongWrapper

from . import attrs, prdb
from .async_updater import AsyncUpdater, TaskResult
from .config import Config
from .errors import Error, ErrorCode
from .prdb import DBRecord

from .helpers import (
    FPContext,
    is_exportable,
    is_updatable,
)
from .trace import print_d, print_e, print_thread_id, print_w

# Note: Check the primary QL file: quodlibet/formats/_audio.py


class AsyncUpdChanged(AsyncUpdater[FPContext]):
    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config

    @override
    def _create_context(self) -> FPContext:
        return FPContext(self._cancellable)

    @override
    def _processor(self, ctx: FPContext, song: SongWrapper) -> bool | Error:

        db_record: DBRecord | None = None
        fp_id: int
        basename: str
        rating: int

        # Ensure the fingerprint of the song
        if attrs.FP_ID not in song:
            filename = song[attrs.FILENAME]

            fp = ctx.calc(filename)
            if fp is None:
                return Error(ErrorCode.FINGERPRINT_ERROR)

            db_records = prdb.get_songs_by_hash(
                self._config.db_path, self._config.sqlite_ext_lib, fp.hash(), 3
            )

            # Is the song already in the PRDB?
            for r in db_records:
                if r.fp == fp:
                    db_record = r
                    break

            # It's new fingeprint, updating of other QL-songs is not needed - return False
            if db_record is None:
                basename: str = song(attrs.BASENAME)
                rating: int = int(song(attrs.RATING) * attrs.RAITING_SCALE)
                db_record = prdb.add_song(self._config.db_path, basename, rating, fp)
                song[attrs.FP_ID] = db_record.fp_id
                return False

            # The fingerprint is in the DB, update the song by values from the DB
            song[attrs.FP_ID] = db_record.fp_id
            fp_id = db_record.fp_id
            basename = song(attrs.BASENAME)
            if db_record.rating == 0:
                rating = int(song(attrs.RATING) * attrs.RAITING_SCALE)
            else:
                song[attrs.RATING] = db_record.rating / attrs.RAITING_SCALE
                rating = db_record.rating
        else:
            fp_id = song[attrs.FP_ID]
            basename = song(attrs.BASENAME)
            rating = int(song(attrs.RATING) * attrs.RAITING_SCALE)

        if prdb.update_song_if_different(self._config.db_path, fp_id, basename, rating):
            # The DB record has been updated, it is needed to update duplicated songs
            # in the QLDB
            return True

        return False

    @override
    def _on_task_result_impl(self, result: TaskResult) -> bool:
        if not result.succeeded:
            return False

        assert app.library and isinstance(app.library, SongLibrary)

        # Find duplicated songs (with the same fingerprint)
        dups: list[SongWrapper] = []

        for song in result.succeeded:
            assert attrs.FP_ID in song

            fp_id = song[attrs.FP_ID]
            rating: float = song(attrs.RATING)

            for s in app.library.values():
                if not is_updatable(s):
                    continue

                if attrs.FP_ID not in s:
                    continue

                # raings in QLDB are in float, thus dorect comparing is not applicable
                # use Epsilon checking instead
                if s[attrs.FP_ID] == fp_id and (s.key != song.key):
                    if abs(s(attrs.RATING) - rating) > attrs.EPSILON:
                        s[attrs.RATING] = rating
                        dups.append(SongWrapper(s))

        # Send notification about changed songs
        if dups:
            app.library.changed(dups)

        return False


class AsyncUpdAdded(AsyncUpdater[FPContext]):
    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config

    @override
    def _create_context(self) -> FPContext:
        return FPContext(self._cancellable)

    @override
    def _processor(self, ctx: FPContext, song: SongWrapper) -> bool | Error:
        filename = song[attrs.FILENAME]

        fp = ctx.calc(filename)

        if fp is None:
            return Error(ErrorCode.FINGERPRINT_ERROR)

        db_records = prdb.get_songs_by_hash(
            self._config.db_path, self._config.sqlite_ext_lib, fp.hash(), 3
        )
        print_d(f"There are {len(db_records)} records in  the QLDB with same hash")

        db_record: DBRecord | None = None
        # Is the song already in the PRDB?
        for r in db_records:
            if r.fp == fp:
                db_record = r
                break

        if db_record is None:
            basename: str = song(attrs.BASENAME)
            rating: int = int(song(attrs.RATING) * attrs.RAITING_SCALE)
            db_record = prdb.add_song(self._config.db_path, basename, rating, fp)
            song[attrs.FP_ID] = db_record.fp_id
            return False

        song[attrs.FP_ID] = db_record.fp_id
        song[attrs.RATING] = db_record.rating / attrs.RAITING_SCALE

        return True


class PluginImpl:
    _config: Config

    _upd_changed: AsyncUpdChanged

    _upd_added: AsyncUpdAdded

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._upd_changed = AsyncUpdChanged(config)
        self._upd_added = AsyncUpdAdded(config)

        db_path = self._config.db_path
        if not Path(db_path).is_file():
            # Create new local database
            prdb.create_db(db_path)

    def stop(self) -> None:
        self._upd_changed.stop()
        self._upd_added.stop()

    def on_added(self, songs: list[SongWrapper]) -> None:
        print_thread_id()

        # Assign stats from PRDB to the recently added songs (for songs, whose
        # fingerprints are exist in the DB)
        songs_to_update = [song for song in songs if is_updatable(song)]
        self._upd_added.append(songs_to_update)

    def on_changed(self, songs: list[SongWrapper]) -> None:
        print_thread_id()

        # TODO to think about a single _cancellable member for the plugin
        # and the both updaters. Something like:
        # if self._cancellable.is_cancelled():
        #     return

        # Reduce songs list and get applicable
        songs_to_export = [song for song in songs if is_exportable(song)]

        if len(songs_to_export) == 0:
            # Nothing to update
            return

        self._upd_changed.append(songs_to_export)
