# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from typing import override
from collections.abc import Collection, Sequence

from gi.repository.Gio import Cancellable
from quodlibet.util.songwrapper import SongWrapper
from quodlibet.plugins.songshelpers import is_a_file, is_finite

from . import attrs

from .acoustic_fp import AcousticFingerprint
from .async_updater import Context
from .errors import Error, ErrorCode
from .trace import print_d

type SongStats = tuple[int, int, int, int, int, str]

# Indices of values within the SongStats tuple
IDX_LAST_PLAYED_STAMP = 0
IDX_LAST_STARTED_STAMP = 1
IDX_PLAY_COUNT = 2
IDX_RATING = 3
IDX_SKIP_COUNT = 4
IDX_PLAYLISTS = 5


class FPContext(Context):
    fp_reader: AcousticFingerprint

    def __init__(self, cancellable: Cancellable) -> None:
        super().__init__(cancellable)
        self.fp_reader = AcousticFingerprint()

    @override
    def delete(self) -> None:
        self.fp_reader.close()
        del self.fp_reader


def calc_fp(ctx: FPContext, song: SongWrapper) -> str | Error:
    """
    Calculates fingerprint and set it to the song.

    The method calculates a fingerprint of the song and assign its value to the
    corresponding song's attribute (attrs.FINGERPRINT).

    Args:
        ctx - Context, that provides AcousticFingerprint object, to calculate the
        fingerprint.
    Returns:
        str - calculated fingerprint
        an Error object in case of error
    """

    filename = song[attrs.FILENAME]
    song_dur: float = song(attrs.LENGTH)
    res, value = ctx.fp_reader.calc_fingerprint(ctx.cancellable, filename, song_dur)
    if not res:
        return Error(ErrorCode.FINGERPRINT_ERROR, value)

    song[attrs.FINGERPRINT] = value

    return value


def get_or_calc_fp(ctx: FPContext, song: SongWrapper) -> str | Error:
    """
    Ensure the fingerprint of the song.

    The method either gets existing fingerprint of the song or calculates one if it
    does not exist.

    Args:
        ctx - Context, that provides AcousticFingerprint object, to calculate the
        fingerprint.
    Returns:
        str - calculated fingerprint
        an Error object in case of error
    """

    if attrs.FINGERPRINT in song:
        fp = str(song(attrs.FINGERPRINT))
        # print_d(f"Existing FP: {fp}")
        return fp

    return calc_fp(ctx, song)


def get_song_stats(song: SongWrapper) -> SongStats:
    lp, ls, pc, rt, sc = 0, 0, 0, 0, 0
    pl = ""

    if attrs.LAST_PLAYED_STAMP in song:
        lp = song(attrs.LAST_PLAYED_STAMP)
    if attrs.LAST_STARTED_STAMP in song:
        ls = song(attrs.LAST_STARTED_STAMP)
    if attrs.PLAY_COUNT in song:
        pc = song(attrs.PLAY_COUNT)
    if attrs.RATING in song:
        rt = song(attrs.RATING)
    if attrs.SKIP_COUNT in song:
        sc = song(attrs.SKIP_COUNT)
    if attrs.PLAYLISTS in song:
        pl = song(attrs.PLAYLISTS)

    return (lp, ls, pc, rt, sc, pl)


def to_stats(vals: Sequence) -> SongStats:
    # len(SongStats) = 6
    assert len(vals) == 6
    return (*vals,)


def is_equal(l: SongStats, r: Collection) -> bool:
    assert len(l) == len(r)
    return all(l_elem == r_elem for l_elem, r_elem in zip(l, r, strict=True))


def is_updatable(song: SongWrapper) -> bool:
    return is_finite(song) and is_a_file(song)


def is_exportable(song: SongWrapper) -> bool:
    return (
        is_finite(song)
        and is_a_file(song)
        and (
            attrs.LAST_PLAYED_STAMP in song
            or attrs.LAST_STARTED_STAMP in song
            or attrs.PLAY_COUNT in song
            or attrs.RATING in song
            or attrs.SKIP_COUNT in song
            or attrs.PLAYLISTS in song
        )
    )


class Record:
    def __init__(
        self,
        song_id: int,
        fp: str,
        created_ts: int,
        updated_ts: int,
        basename: str,
        dirname: str,
        added_ts: int,
        stats: SongStats,
    ):
        self.song_id = song_id
        self.fp = fp
        self.created_ts = created_ts
        self.updated_ts = updated_ts
        self.basename = basename
        self.dirname = dirname
        self.added_ts = added_ts
        self.stats = stats
        # self.lp, self.ls, self.pc, self.rt, self.sc, self.pl = stats

    def __eq__(self, other):
        if not isinstance(other, Record):
            return NotImplemented
        if self.fp != other.fp:
            return False
        return is_equal(self.stats, other.stats)

    def __hash__(self) -> int:
        return hash(self.fp)

    def __iter__(self):
        # Yield the values you want to be unpacked
        lp, ls, pc, rt, sc, pl = self.stats

        yield lp # LAST_PLAYED_STAMP
        yield ls # LAST_STARTED_STAMP
        yield pc # PLAY_COUNT
        yield rt # RATING
        yield sc # SKIP_COUNT
        yield pl # PLAYLISTS

    def is_younger(self, other: "Record") -> bool:
        assert isinstance(other, Record)
        assert self.fp == other.fp

        if self.stats[IDX_LAST_PLAYED_STAMP] > other.stats[IDX_LAST_PLAYED_STAMP]:
            return True
        if self.stats[IDX_LAST_PLAYED_STAMP] < other.stats[IDX_LAST_PLAYED_STAMP]:
            return False
        if self.stats[IDX_LAST_STARTED_STAMP] > other.stats[IDX_LAST_STARTED_STAMP]:
            return True
        if self.stats[IDX_LAST_STARTED_STAMP] < other.stats[IDX_LAST_STARTED_STAMP]:
            return False
        if self.stats[IDX_SKIP_COUNT] > other.stats[IDX_SKIP_COUNT]:
            return True
        if self.stats[IDX_SKIP_COUNT] < other.stats[IDX_SKIP_COUNT]:
            return False
        if self.stats[IDX_PLAY_COUNT] > other.stats[IDX_PLAY_COUNT]:
            return True
        if self.stats[IDX_PLAY_COUNT] < other.stats[IDX_PLAY_COUNT]:
            return False
        if self.updated_ts > other.updated_ts:
            return True
        if self.updated_ts < other.updated_ts:
            return False
        if self.created_ts > other.created_ts:
            return True

        return False


def update_song_stats(
    song: SongWrapper, new_stats: Sequence | SongStats | Record
) -> bool:

    stats: Sequence | SongStats

    if isinstance(new_stats, Record):
        stats = new_stats.stats
    else:
        stats = new_stats

    existing_stats = get_song_stats(song)
    if not is_equal(existing_stats, stats):
        song[attrs.LAST_PLAYED_STAMP] = stats[IDX_LAST_PLAYED_STAMP]
        song[attrs.LAST_STARTED_STAMP] = stats[IDX_LAST_STARTED_STAMP]
        song[attrs.PLAY_COUNT] = stats[IDX_PLAY_COUNT]
        song[attrs.RATING] = stats[IDX_RATING] / attrs.RAITING_SCALE
        song[attrs.SKIP_COUNT] = stats[IDX_SKIP_COUNT]
        song[attrs.PLAYLISTS] = stats[IDX_PLAYLISTS]
        return True
    return False
