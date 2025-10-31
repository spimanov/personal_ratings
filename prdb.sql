--
-- File generated with SQLiteStudio v3.4.17 on Wed Oct 1 13:51:57 2025
--
-- Text encoding used: UTF-8
--
PRAGMA foreign_keys = off;
BEGIN TRANSACTION;

-- Table: songs
CREATE TABLE IF NOT EXISTS songs (
    song_id     INTEGER   PRIMARY KEY ASC AUTOINCREMENT
                          UNIQUE,
    fingerprint TEXT (40) NOT NULL
                          UNIQUE,
    basename    TEXT,
    dirname     TEXT,
    added       INTEGER,
    lastplayed  INTEGER,
    laststarted INTEGER,
    playcount   INTEGER,
    rating      INTEGER,
    skipcount   INTEGER,
    playlists   TEXT,
    created_at  INTEGER DEFAULT (unixepoch() )
                        NOT NULL,
    updated_at  INTEGER
);


COMMIT TRANSACTION;
PRAGMA foreign_keys = on;
