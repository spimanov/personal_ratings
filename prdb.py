# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import sqlite3

from pathlib import Path
from contextlib import closing

from quodlibet.util.songwrapper import SongWrapper

from . import attrs
from .trace import print_d
from .helpers import get_song_stats, is_equal, update_song_stats, to_stats, Record


def create_db(db_path: str):
    script_directory = Path(__file__).resolve().parent
    prdb_sql = script_directory / "prdb.sql"
    with open(prdb_sql) as f:
        sql = f.read()

    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.executescript(sql)

    print_d(f"PRDB has created at {db_path}")


def update_song_in_db(
    db_path: str, fingerprint: str, song: SongWrapper, force=True
) -> bool:

    sql_find = (
        "SELECT song_id, lastplayed, laststarted, "
        "playcount, rating, skipcount, playlists "
        "FROM songs WHERE fingerprint = ?;"
    )

    sql_insert = (
        "INSERT INTO songs "
        "(fingerprint, basename, dirname, added, lastplayed, laststarted, "
        "playcount, rating, skipcount, playlists) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?);"
    )

    sql_update = (
        "UPDATE songs SET "
        "lastplayed = ?, laststarted = ?, "
        "playcount = ?, rating = ?, skipcount = ?, playlists = ?, "
        "updated_at = unixepoch() WHERE song_id = ?;"
    )

    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(sql_find, (fingerprint,))
            record = cursor.fetchone()
            song_stats = get_song_stats(song)
            if record:
                song_id, *vals = record

                if force:
                    if is_equal(song_stats, vals):
                        # Update is not needed
                        return False
                else:
                    if (song_stats[0] <= vals[0]) and (song_stats[1] <= vals[1]):
                        return False

                print_d(f"in DB: {vals}")
                print_d(f"in QL: {song_stats}")

                # Updating data in the db
                cursor.execute(sql_update, song_stats + (song_id,))
            else:
                ins_data = (
                    fingerprint,
                    song(attrs.BASENAME),
                    song(attrs.DIRNAME),
                    song(attrs.DATE_ADDED_STAMP),
                    *song_stats,
                )
                cursor.execute(sql_insert, ins_data)

    print_d(f"Updated DB record for file: {song_stats[0]}, {fingerprint}")
    return True


def update_song_from_db(
    db_path: str, fingerprint: str, song: SongWrapper, force=True
) -> bool:

    sql_find = (
        "SELECT song_id, lastplayed, laststarted, "
        "playcount, rating, skipcount, playlists "
        "FROM songs WHERE fingerprint = ?;"
    )

    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(sql_find, (fingerprint,))
            record = cursor.fetchone()
            if record:
                song_id, *vals = record

                if not force:
                    lp = 0  # last played timestamp
                    ls = 0  # last started timestamp

                    if attrs.LAST_PLAYED_STAMP in song:
                        lp = song(attrs.LAST_PLAYED_STAMP)

                    if attrs.LAST_STARTED_STAMP in song:
                        ls = song(attrs.LAST_STARTED_STAMP)

                    if (lp >= vals[0]) or (ls >= vals[1]):
                        # Update is not needed
                        return False

                if update_song_stats(song, vals):
                    print_d(
                        f"Updated song from DB: {song(attrs.BASENAME)}, {fingerprint}"
                    )
                    return True

    return False


def get_songs(db_path: str) -> list[Record]:

    sql_select_all = (
        "SELECT song_id, fingerprint, created_at, updated_at, basename, dirname, added, "
        "lastplayed, laststarted, playcount, rating, skipcount, playlists "
        "FROM songs;"
    )

    result: list[Record] = []
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(sql_select_all)
            # Fetch all the results
            rows = cursor.fetchall()
            for row in rows:
                (
                    song_id,
                    fp,
                    created_at,
                    updated_at,
                    basename,
                    dirname,
                    added_ts,
                    *vals,
                ) = row

                stats = to_stats(vals)
                result.append(
                    Record(
                        song_id,
                        fp,
                        created_at,
                        updated_at,
                        basename,
                        dirname,
                        added_ts,
                        stats,
                    )
                )

    return result


def update_rec(db_path: str, rec: Record) -> bool:

    sql_find = (
        "SELECT song_id, lastplayed, laststarted, "
        "playcount, rating, skipcount, playlists "
        "FROM songs WHERE fingerprint = ?;"
    )

    sql_insert = (
        "INSERT INTO songs "
        "(fingerprint, basename, dirname, added, lastplayed, laststarted, "
        "playcount, rating, skipcount, playlists) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?);"
    )

    sql_update = (
        "UPDATE songs SET "
        "lastplayed = ?, laststarted = ?, "
        "playcount = ?, rating = ?, skipcount = ?, playlists = ?, "
        "updated_at = unixepoch() WHERE song_id = ?;"
    )

    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(sql_find, (rec.fp,))
            record = cursor.fetchone()
            song_stats = rec.stats
            if record:
                song_id, *vals = record

                if is_equal(song_stats, vals):
                    # Update is not needed
                    return False

                # Updating data in the db
                cursor.execute(sql_update, song_stats + (song_id,))
            else:
                ins_data = (
                    rec.fp,
                    rec.basename,
                    rec.dirname,
                    rec.added_ts,
                    *song_stats,
                )
                cursor.execute(sql_insert, ins_data)

    return True
