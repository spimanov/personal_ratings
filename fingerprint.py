# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import base64
import numpy as np

from typing import Self

from .fp_decompressor import FingerprintDecompressor, RawFP, Bytes
from .trace import print_d

# Useful links
# https://oxygene.sk/2011/01/how-does-chromaprint-work/
# https://willdrevo.com/fingerprinting-and-audio-recognition-with-python/
# https://github.com/worldveil/dejavu
# https://emysound.com/blog/open-source/2020/06/12/how-audio-fingerprinting-works.html


def match_fingerprints(a: RawFP, b: RawFP):
    # https://github.com/acoustid/pg_acoustid/blob/main/acoustid_compare.c
    # https://github.com/acoustid/chromaprint/blob/master/src/fingerprint_matcher.cpp
    ACOUSTID_MAX_BIT_ERROR = 2
    ACOUSTID_MAX_ALIGN_OFFSET = 120

    asize = len(a)  # 948 u32 = 3792 u8
    bsize = len(b)  # 948 u32 = 3792 u8

    # print_d(f"a: {a.nbytes}, b: {b.nbytes}")
    numcounts = asize + bsize + 1
    # counts: np.ndarray[tuple[int], np.dtype[np.int32]] = np.zeros(numcounts, dtype=np.int32)
    counts = np.zeros(numcounts, dtype=np.int32)

    def popcount(x: np.uint32):
        return bin(x).count("1")

    for i in range(asize):
        jbegin = max(0, i - ACOUSTID_MAX_ALIGN_OFFSET)
        jend = min(bsize, i + ACOUSTID_MAX_ALIGN_OFFSET)
        for j in range(jbegin, jend):
            # biterror = popcount(a[i] ^ b[j])
            biterror = (a[i] ^ b[j]).bit_count()
            if biterror <= ACOUSTID_MAX_BIT_ERROR:
                offset = i - j + bsize
                counts[offset] += 1

    topcount = counts.max()
    return topcount / min(asize, bsize)


def unpack_base64_fp(fp_base64: str, dec: FingerprintDecompressor) -> RawFP:
    """Unpack base64 data to a plain uint32 array (UnpackedFPData)"""

    padding_needed = (4 - len(fp_base64) % 4) % 4
    fp_base64_padded = fp_base64 + ("=" * padding_needed)
    # If your input is a string, you need to encode it to bytes first (e.g., using UTF-8)
    # encoded_data_bytes = fp_str.encode('utf-8')
    # Decoding base64 data: urlsafe_b64decode returns `bytes`
    stream_bytes = base64.urlsafe_b64decode(fp_base64_padded)

    fp_stream = np.frombuffer(stream_bytes, dtype=np.uint8)

    fp = dec.decompress(fp_stream)
    # print(
    #     f"base64: {len(fp_base64)} bytes, packed_fp: {len(fp_stream)} bytes,"
    #     f" unpacked_fp.len (u32): {fp.size}, size: {fp.data.nbytes} bytes"
    # )
    # base64: 2520 bytes, packed_fp: 1890 bytes, unpacked_fp.len (u32): 948, size: 3792 bytes

    # The raw fingerprints are fixed. The number of 32-bit integers is going to be:
    # (duration_in_seconds * 11025 - 4096) / 1365 - 15 - 4 + 1  (It can be off +/-1 due
    # to rounding.)

    # The other numbers are from here:
    #
    # https://github.com/acoustid/chromaprint/blob/master/src/fingerprinter_configuration.cpp
    #
    # 11025 = audio sampling rate
    # 4096 = one FFT window size
    # 1365 = increment of the moving FFT window
    # 15 = number of classifiers - 1
    # 4 = number of coefficients in the chromagram smoothing filter - 1
    #
    # The last numbers and the +1 might be wrong, since I don't remember the algorithm
    # exactly, but they add up correctly. If you care about the exact numbers, you will
    # have to work them out from the code.
    # int((120 * 11025 - 4096) / 1365 - 15 - 3 + 1) = 948 (number of u32 integers)

    return fp.data


def sim_hash(data: RawFP) -> np.uint32:
    # https://dev.to/lovestaco/what-is-simhash-58m5
    # https://github.com/acoustid/chromaprint/blob/master/src/simhash.cpp
    # https://github.com/acoustid/chromaprint/blob/master/src/simhash.cpp

    v = np.zeros(32, dtype=np.int32)

    for local_hash in data:
        for j in range(32):
            v[j] += (local_hash >> j) & 1

    threshold = len(data) // 2
    hash = np.uint32(0)

    for i in range(32):
        b = np.uint32(1) if v[i] > threshold else np.uint32(0)
        hash |= b << i

    return hash


def hamming_distance(a: np.uint32, b: np.uint32) -> int:
    return (a ^ b).bit_count()


class Fingerprint:
    _raw_fp: RawFP
    _hash: np.uint32

    def __init__(self, blob: bytes | RawFP, fp_hash: int | None) -> None:
        if isinstance(blob, bytes):
            self._raw_fp = np.frombuffer(blob, dtype=np.uint32)
        else:
            self._raw_fp = blob

        if fp_hash is None:
            self._hash = sim_hash(self._raw_fp)
        else:
            self._hash = np.uint32(fp_hash)

    @classmethod
    def from_base64(cls, fp_base64: str, dec: FingerprintDecompressor) -> Self:
        fp = unpack_base64_fp(fp_base64, dec)
        return cls(fp, None)

    def as_blob(self) -> Bytes:
        """get RawFP as a view of byte values. Used to store in DB"""
        return self._raw_fp.view(np.uint8)

    def hash(self) -> int:
        return int(self._hash)

    def __eq__(self, other: object):
        # Check if the 'other' object is an instance of the same class
        # (optional but recommended)
        if not isinstance(other, Fingerprint):
            # Returning NotImplemented allows Python to try the reverse comparison
            # or fall back to default behavior.
            return NotImplemented

        if hamming_distance(self._hash, other._hash) > 3:
            return False

        equal_ratio = match_fingerprints(self._raw_fp, other._raw_fp)

        # print(f"equal_ratio: {equal_ratio}")
        return equal_ratio >= 0.90
