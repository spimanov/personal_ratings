# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import sqlite3
import time

from pathlib import Path
from contextlib import closing

from .trace import print_d
from .fingerprint import Fingerprint


class DBRecordBase:
    fp_id: int
    basename: str
    rating: int
    created_at: int
    updated_at: int | None

    def __init__(
        self,
        fp_id: int,
        basename: str,
        rating: int,
        created_at: int,
        updated_at: int | None,
    ) -> None:
        self.fp_id = fp_id
        self.basename = basename
        self.rating = rating
        self.created_at = created_at
        self.updated_at = updated_at

    def timestamp(self) -> int:
        if self.updated_at is None:
            return 0
        return self.updated_at


class DBRecord(DBRecordBase):
    fp: Fingerprint

    def __init__(
        self,
        fp_id: int,
        basename: str,
        rating: int,
        fp_hash: int | None,
        fp: Fingerprint | bytes,
        created_at: int,
        updated_at: int | None,
    ) -> None:
        super().__init__(fp_id, basename, rating, created_at, updated_at)

        if isinstance(fp, bytes):
            self.fp = Fingerprint(fp, fp_hash)
        elif isinstance(fp, Fingerprint):
            self.fp = fp
        else:
            raise sqlite3.DatabaseError("create DBRecord: invalid FP data type")


def create_db(db_path: str):
    script_directory = Path(__file__).resolve().parent
    prdb_sql = script_directory / "prdb.sql"
    with open(prdb_sql) as f:
        create_db_query = f.read()

    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.executescript(create_db_query)

    print_d(f"New PRDB has been created on: '{db_path}'")


def add_empty_song(db_path: str, basename: str, fp: Fingerprint) -> DBRecord:
    """Create a record int he PRDB, but its rating is unspecified"""

    insert_query = (
        "INSERT INTO songs (basename, fp_hash, fingerprint, created_at) "
        "VALUES (?, ?, ?, ?) RETURNING id;"
    )

    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()

            # Get the current Unix epoch timestamp as an integer
            # time.time() returns a float, so we cast it to an int for second precision
            created_at = int(time.time())

            cursor.execute(insert_query, (basename, fp.hash(), fp.as_blob(), created_at))
            row = cursor.fetchone()
            if not row:
                raise sqlite3.DatabaseError("add_song: insert_query returned None")

            (song_id,) = row
            # print_d(f"Added new song into DB {db_path}: #{song_id}: '{basename}'")

            return DBRecord(
                song_id,
                basename,
                0,
                None,
                fp,
                created_at,
                None,
            )


def add_song(db_path: str, basename: str, rating: int, fp: Fingerprint) -> DBRecord:

    insert_query = (
        "INSERT INTO songs (basename, rating, fp_hash, fingerprint, created_at,"
        " updated_at) VALUES (?, ?, ?, ?, ?, ?) RETURNING id;"
    )

    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()

            # Get the current Unix epoch timestamp as an integer
            # time.time() returns a float, so we cast it to an int for second precision
            created_at = int(time.time())

            cursor.execute(
                insert_query,
                (basename, rating, fp.hash(), fp.as_blob(), created_at, created_at),
            )
            row = cursor.fetchone()
            if not row:
                raise sqlite3.DatabaseError("add_song: insert_query returned None")

            (song_id,) = row
            # print_d(f"Added new song into DB {db_path}: #{song_id}: '{basename}'")

            return DBRecord(
                song_id,
                basename,
                rating,
                None,
                fp,
                created_at,
                created_at,
            )


def add_record(db_path: str, rec: DBRecord) -> DBRecord:

    insert_query = (
        "INSERT INTO songs (basename, rating, fp_hash, fingerprint, created_at,"
        " updated_at) VALUES (?, ?, ?, ?, ?, ?) RETURNING id;"
    )

    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()

            cursor.execute(
                insert_query,
                (
                    rec.basename,
                    rec.rating,
                    rec.fp.hash(),
                    rec.fp.as_blob(),
                    rec.created_at,
                    rec.updated_at,
                ),
            )
            row = cursor.fetchone()
            if not row:
                raise sqlite3.DatabaseError("add_song: insert_query returned None")

            (song_id,) = row
            # print_d(f"Added new song into DB {db_path}: #{song_id}: '{rec.basename}'")

            return DBRecord(
                song_id,
                rec.basename,
                rec.rating,
                None,
                rec.fp,
                rec.created_at,
                rec.updated_at,
            )


def force_song_update(db_path: str, song: DBRecordBase) -> None:
    """Force record update (all columns, including created_at and updated_at)"""

    update_query = (
        "UPDATE songs SET basename = ?, rating = ?, updated_at = ? WHERE id = ?;"
    )

    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                update_query,
                (
                    song.basename,
                    song.rating,
                    song.updated_at,
                    song.fp_id,
                ),
            )
            print_d(
                f"Forcibly updated song in DB {db_path}: #{song.fp_id}, rating:"
                f" {song.rating}, basename: '{song.basename}'"
            )


def update_song(db_path: str, song_id: int, basename: str, rating: int) -> bool:
    """Forcibly update a record in DB"""

    update_query = (
        "UPDATE songs SET "
        "basename = ?, rating = ?, "
        "updated_at = unixepoch() WHERE "
        "id = ?;"
    )

    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                update_query,
                (basename, rating, song_id),
            )
            conn.commit()

            if cursor.rowcount > 0:
                print_d(
                    f"Updated song in DB {db_path}: #{song_id}, rating: {rating},"
                    f" basename: '{basename}'"
                )
                return True

    return False


def update_song_if_different(
    db_path: str, song_id: int, basename: str, rating: int
) -> bool:
    """Update a record in DB only if it is different"""

    update_query = (
        "UPDATE songs SET "
        "basename = ?, rating = ?, "
        "updated_at = unixepoch() WHERE "
        "id = ? AND ("
        "(basename != ?) OR (updated_at IS NULL) "
        " OR ((updated_at IS NOT NULL) and (rating != ?))"
        ");"
    )

    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                update_query,
                (basename, rating, song_id, basename, rating),
            )
            conn.commit()

            if cursor.rowcount > 0:
                print_d(
                    f"Updated song in DB {db_path}: #{song_id}, rating: {rating},"
                    f" basename: '{basename}'"
                )
                return True

    return False


def get_song(db_path: str, fp_id: int) -> DBRecordBase:

    select_one_query = (
        "SELECT id, basename, rating, created_at, updated_at FROM songs WHERE id = ?;"
    )

    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(select_one_query, (fp_id,))

            row = cursor.fetchone()
            if row is None:
                raise sqlite3.DatabaseError(
                    f"get_song: record with fp_id #{fp_id} not found"
                )

            return DBRecordBase(*row)


def get_songs(db_path: str) -> list[DBRecord]:

    select_all_query = (
        "SELECT id, basename, rating, fp_hash, fingerprint, created_at, updated_at "
        "FROM songs;"
    )

    result: list[DBRecord] = []
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(select_all_query)

            # Fetch all results
            rows = cursor.fetchall()
            for row in rows:
                result.append(DBRecord(*row))

    return result


def get_songs_not_older(db_path: str, timestamp: int) -> list[DBRecord]:

    select_query = (
        "SELECT id, basename, rating, fp_hash, fingerprint, created_at, updated_at "
        "FROM songs "
        "WHERE ((updated_at IS NOT NULL) AND (updated_at >= ?)) OR (created_at >= ?);"
    )

    result: list[DBRecord] = []
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(select_query, (timestamp, timestamp))

            # Fetch all results
            rows = cursor.fetchall()
            for row in rows:
                result.append(DBRecord(*row))

    return result


def get_songs_by_hash(
    db_path: str, ext_path: str, hash: int, distance: int
) -> list[DBRecord]:
    """sqlite3_phhammdist_init"""
    ext_load_query = f"SELECT load_extension('{ext_path}', 'sqlite3_phhammdist_init');"

    select_query = (
        "SELECT id, basename, rating, fp_hash, fingerprint, created_at, updated_at "
        "FROM songs WHERE phhammdist(fp_hash, ?) <= ?;"
    )

    result: list[DBRecord] = []
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.enable_load_extension(True)
            conn.execute(ext_load_query)

            cursor = conn.cursor()
            cursor.execute(select_query, (hash, distance))

            # Fetch all results
            rows = cursor.fetchall()
            for row in rows:
                result.append(DBRecord(*row))

    return result
