# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from pathlib import Path

from gi.repository.Gio import Cancellable

from quodlibet import app
from quodlibet.library.song import SongLibrary
from quodlibet.util.songwrapper import SongWrapper

from . import attrs, prdb
from .config import Config
from .errors import Error, ErrorCode
from .helpers import (
    FPContext,
    are_not_equal,
    is_updatable,
    rating_to_float,
    rating_to_int,
)
from .prdb import DBRecord
from .trace import print_d, print_e, print_thread_id, print_w

# Note: Check the primary QL file: quodlibet/formats/_audio.py


class PluginImpl:
    _config: Config
    _cancellable: Cancellable

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._cancellable = Cancellable()
        self._ctx = FPContext(self._cancellable)

        db_path = self._config.db_path
        if not Path(db_path).is_file():
            # Create new local database
            prdb.create_db(db_path)

    def stop(self) -> None:
        self._cancellable.cancel()

    def _add_processor(self, ctx: FPContext, song: SongWrapper) -> bool | Error:
        filename = song[attrs.FILENAME]

        fp = ctx.calc(filename)

        if fp is None:
            return Error(ErrorCode.FINGERPRINT_ERROR)

        db_records = prdb.get_songs_by_hash(
            self._config.db_path, self._config.sqlite_ext_lib, fp.hash(), 1
        )

        db_record: DBRecord | None = None
        # Is the song already in the PRDB?
        for r in db_records:
            if r.fp == fp:
                db_record = r
                break

        if db_record is None:
            # If song is really a new one (for the QLDB), add it to the PRDB, but without
            # the song's rating
            basename: str = song(attrs.BASENAME)
            db_record = prdb.add_empty_song(self._config.db_path, basename, fp)
            song[attrs.FP_ID] = db_record.fp_id
            print_d(f"OnAdd: new: {filename}")
            return True

        # Number of records in the DB with the same hash
        shc = ""
        if len(db_records) > 0:
            shc = f" (exist: {len(db_records)})"

        song[attrs.FP_ID] = db_record.fp_id
        if db_record.updated_at is not None:
            song[attrs.RATING] = rating_to_float(db_record.rating)
            print_d(
                f"OnAdd:{shc}: {filename}, rating: {db_record.rating}"
            )
        else:
            print_d(f"OnAdd:{shc}: {filename}")

        return True

    def on_added(self, songs: list[SongWrapper]) -> None:
        print_thread_id()
        print_d(f"len(songs): {len(songs)}")

        for s in songs:
            # print_d(s[attrs.FILENAME])
            if not is_updatable(s):
                continue
            if self._cancellable.is_cancelled():
                return
            self._add_processor(self._ctx, s)

    def _change_processor(self, ctx: FPContext, song: SongWrapper) -> bool | Error:

        # Update is called for a song, which does not have fingerprint
        # it is possible if: fingerprint was not generated or file was changed
        # (in case of changed file, QL creates new song item and drops all custom tags)
        if attrs.FP_ID not in song:
            filename = song[attrs.FILENAME]

            fp = ctx.calc(filename)
            if fp is None:
                return Error(ErrorCode.FINGERPRINT_ERROR)

            db_records = prdb.get_songs_by_hash(
                self._config.db_path, self._config.sqlite_ext_lib, fp.hash(), 1
            )

            db_record: DBRecord | None = None
            # Is the song already in the PRDB?
            for r in db_records:
                if r.fp == fp:
                    db_record = r
                    break

            if db_record is None:
                # It's new fingeprint in the PRDB
                basename: str = song(attrs.BASENAME)
                if attrs.RATING in song:
                    rating: int = rating_to_int(song(attrs.RATING))
                    db_record = prdb.add_song(self._config.db_path, basename, rating, fp)
                    print_d(
                        f"OnChange: added new FP: {db_record.fp_id} for {filename},"
                        f" rating: {rating}"
                    )
                else:
                    db_record = prdb.add_empty_song(self._config.db_path, basename, fp)
                    print_d(f"OnChange: added new FP: {db_record.fp_id} for {filename}")

                song[attrs.FP_ID] = db_record.fp_id
                # This is the first song in the PRDB, thus there are no songs with the
                # same Fingerprint in the QLDB. So, nothing to update - return False
                return False

            # The fingerprint is already in the DB, update the song rating by the value from the DB
            song[attrs.FP_ID] = db_record.fp_id

            if db_record.updated_at is not None:
                song[attrs.RATING] = rating_to_float(db_record.rating)
                print_d(
                    f"OnChange: existing FP: {db_record.fp_id} for {filename}, rating:"
                    f" {db_record.rating}"
                )
            else:
                print_d(f"OnChange: existing FP: {db_record.fp_id} for {filename}")

            return False

        basename = song(attrs.BASENAME)

        if attrs.RATING in song:
            fp_id = song[attrs.FP_ID]
            rating = rating_to_int(song(attrs.RATING))
            if prdb.update_song_if_different(
                self._config.db_path, fp_id, basename, rating
            ):
                # The DB record has been updated, it is needed to update duplicated songs
                # in the QLDB
                print_d(f"OnChange: updated: {basename}, rating: {rating}")
                return True

        print_d(f"OnChange: not updated: {basename}")
        return False

    def on_changed(self, songs: list[SongWrapper]) -> None:
        print_thread_id()
        print_d(f"len(songs): {len(songs)}")

        # TODO to think about a single _cancellable member for the plugin
        # and the both updaters. Something like:
        # if self._cancellable.is_cancelled():
        #     return
        for s in songs:
            # print_d(s[attrs.FILENAME])
            if not is_updatable(s):
                continue
            if self._cancellable.is_cancelled():
                return
            if self._change_processor(self._ctx, s):
                self._on_song_updated(s)

    def _on_song_updated(self, song: SongWrapper) -> None:

        assert app.library and isinstance(app.library, SongLibrary)

        # Find duplicated songs (with the same fingerprint)
        dups: list[SongWrapper] = []

        assert attrs.FP_ID in song

        fp_id = song[attrs.FP_ID]
        rating: float = song(attrs.RATING)

        for s in app.library.values():
            if not is_updatable(s):
                continue

            if attrs.FP_ID not in s:
                continue

            if s[attrs.FP_ID] != fp_id:
                continue

            if s.key == song.key:
                continue

            # raings in QLDB are in float, thus dorect comparing is not applicable
            # use Epsilon checking instead

            if are_not_equal(s(attrs.RATING), rating):
                to_update = SongWrapper(s)
                to_update[attrs.RATING] = rating
                dups.append(to_update)

        # Send notification about changed songs
        if dups:
            app.library.changed(dups)
