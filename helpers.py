# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from typing import override

from gi.repository.Gio import Cancellable
from quodlibet.plugins.songshelpers import is_a_file, is_finite
from quodlibet.util.songwrapper import SongWrapper

from . import attrs
from .fingerprint import Fingerprint
from .fp_calculator import FingerprintCalculator
from .fp_decompressor import FingerprintDecompressor

from .async_updater import Context
from .trace import print_d, print_e


class FPContext(Context):
    _fp_calc: FingerprintCalculator
    _dec: FingerprintDecompressor

    def __init__(self, cancellable: Cancellable) -> None:
        super().__init__(cancellable)
        self._fp_calc = FingerprintCalculator(cancellable)
        self._dec = FingerprintDecompressor()

    @override
    def delete(self) -> None:
        self._fp_calc.close()
        del self._fp_calc

    def calc(self, filename: str) -> Fingerprint | None:
        try:
            fp_base64 = self._fp_calc.open().calc(filename)
            fp = Fingerprint.from_base64(fp_base64, self._dec)
            return fp
        except Exception as err:
            print_e(f"Unhandled exception: {err}")
        return None


def is_updatable(song: SongWrapper) -> bool:
    return is_finite(song) and is_a_file(song)


def is_exportable(song: SongWrapper) -> bool:
    return is_finite(song) and is_a_file(song) and attrs.RATING in song
