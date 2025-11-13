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
from .errors import Error
from .helpers import (
    FPContext,
    calc_fp,
    get_or_calc_fp,
    get_song_stats,
    is_exportable,
    is_updatable,
    update_song_stats,
)
from .trace import print_d, print_e, print_thread_id, print_w


class AsyncUpdChanged(AsyncUpdater[FPContext]):
    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config

    @override
    def _create_context(self) -> FPContext:
        return FPContext(self._cancellable)

    @override
    def _processor(self, ctx: FPContext, song: SongWrapper) -> bool | Error:
        # Ensure the fingerprint of the song
        fp = get_or_calc_fp(ctx, song)
        if isinstance(fp, Error):
            return fp

        if prdb.update_song_in_db(self._config.db_path, fp, song):
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
            assert attrs.FINGERPRINT in song
            song_fp = song(attrs.FINGERPRINT)
            song_stats = get_song_stats(song)

            for s in app.library.values():
                if not is_updatable(s):
                    continue

                if attrs.FINGERPRINT not in s:
                    continue

                if s(attrs.FINGERPRINT) == song_fp and (s.key != song.key):
                    if update_song_stats(s, song_stats):
                        dups.append(SongWrapper(s))

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
        filename = song(attrs.FILENAME)
        if attrs.FINGERPRINT in song:
            fp = str(song(attrs.FINGERPRINT))
            # This is weird -> because I assume that the FP does not exist at the moment
            print_w(f"FP exists on the song: {filename}, fp: {fp}")
            return False

        # Calculate fingerprint
        fp = calc_fp(ctx, song)
        if isinstance(fp, Error):
            return fp

        return prdb.update_song_from_db(self._config.db_path, fp, song)


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
