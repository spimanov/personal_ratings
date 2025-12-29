# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import numpy as np
from quodlibet.util import print_e

type Bytes = np.ndarray[tuple[int], np.dtype[np.uint8]]
""" Byte array"""

type RawFP = np.ndarray[tuple[int], np.dtype[np.uint32]]
""" 1D array to keep unpacked fingerprint """


class UnpackedFP:
    size: int
    algorithm: int
    data: RawFP

    def __init__(self, size: int, algorithm: int, data: RawFP) -> None:
        self.size = size
        self.algorithm = algorithm
        self.data = data


class DecompressFPError(Exception):
    def __init__(self, msg: str) -> None:
        super().__init__("FPDecompressError: " + msg)


# https://github.com/acoustid/chromaprint/blob/master/src/fingerprint_decompressor.cpp
class FingerprintDecompressor:

    _size: int
    _algorithm: int

    _kMaxNormalValue = 7
    _kNormalBits = 3
    _kExceptionBits = 5

    def __init__(self):
        self._size = 0
        self._algorithm = 0

    # https://github.com/acoustid/chromaprint/blob/master/src/fingerprint_decompressor.cpp#L39
    def _unpack_header(self, fp_stream: Bytes):
        assert len(fp_stream) >= 4

        self._algorithm = fp_stream[0]
        self._size = (
            (int(fp_stream[1]) << 16) | (int(fp_stream[2]) << 8) | (int(fp_stream[3]))
        )

    def _unpack_bits(self, bits: Bytes) -> RawFP:
        # Fill the result array by -1
        result: RawFP = np.full(self._size, 0xFFFFFFFF, dtype=np.uint32)

        i = 0
        last_bit = np.uint32(0)
        value = np.uint32(0)
        for bit in bits:
            if bit == 0:
                result[i] = value
                last_bit = 0
                i += 1
            else:
                last_bit += np.uint32(bit)
                value = value ^ (1 << (last_bit - 1))

        return result

    def _get_unpacked_int3_array_size(self, packed_size: int) -> int:
        return packed_size * 8 // 3

    def _get_packed_int3_array_size(self, unpacked_size: int) -> int:
        return (unpacked_size * 3 + 7) // 8

    def _get_unpacked_int5_array_size(self, packed_size: int) -> int:
        return packed_size * 8 // 5

    def _get_packed_int5_array_size(self, unpacked_size: int) -> int:
        return (unpacked_size * 5 + 7) // 8

    def _unpack_int3_array(self, fp_stream: Bytes) -> Bytes:
        num_bytes = self._get_unpacked_int3_array_size(len(fp_stream))
        dest: Bytes = np.empty(num_bytes, dtype=np.uint8)

        size = len(fp_stream)
        src = fp_stream
        in_idx = 0
        out_idx = 0

        while size >= 3:
            s0 = src[in_idx]
            in_idx += 1
            s1 = src[in_idx]
            in_idx += 1
            s2 = src[in_idx]
            in_idx += 1

            dest[out_idx] = s0 & 0x07
            out_idx += 1
            dest[out_idx] = (s0 & 0x38) >> 3
            out_idx += 1
            dest[out_idx] = ((s0 & 0xC0) >> 6) | ((s1 & 0x01) << 2)
            out_idx += 1
            dest[out_idx] = (s1 & 0x0E) >> 1
            out_idx += 1
            dest[out_idx] = (s1 & 0x70) >> 4
            out_idx += 1
            dest[out_idx] = ((s1 & 0x80) >> 7) | ((s2 & 0x03) << 1)
            out_idx += 1
            dest[out_idx] = (s2 & 0x1C) >> 2
            out_idx += 1
            dest[out_idx] = (s2 & 0xE0) >> 5
            out_idx += 1

            size -= 3

        if size == 2:
            s0 = src[in_idx]
            in_idx += 1
            s1 = src[in_idx]
            in_idx += 1

            dest[out_idx] = s0 & 0x07
            out_idx += 1
            dest[out_idx] = (s0 & 0x38) >> 3
            out_idx += 1
            dest[out_idx] = ((s0 & 0xC0) >> 6) | ((s1 & 0x01) << 2)
            out_idx += 1
            dest[out_idx] = (s1 & 0x0E) >> 1
            out_idx += 1
            dest[out_idx] = (s1 & 0x70) >> 4
            out_idx += 1
        elif size == 1:
            s0 = src[in_idx]
            in_idx += 1

            dest[out_idx] = s0 & 0x07
            out_idx += 1
            dest[out_idx] = (s0 & 0x38) >> 3
            out_idx += 1

        return dest

    def _unpack_int5_array(self, fp_stream: Bytes, num_dest: int) -> Bytes:
        num_bytes = self._get_unpacked_int5_array_size(
            self._get_packed_int5_array_size(num_dest)
        )
        dest: Bytes = np.empty(num_bytes, dtype=np.uint8)

        size = len(fp_stream)
        src = fp_stream
        in_idx = 0
        out_idx = 0

        while size >= 5:
            s0 = src[in_idx]
            in_idx += 1
            s1 = src[in_idx]
            in_idx += 1
            s2 = src[in_idx]
            in_idx += 1
            s3 = src[in_idx]
            in_idx += 1
            s4 = src[in_idx]
            in_idx += 1

            dest[out_idx] = s0 & 0x1F
            out_idx += 1
            dest[out_idx] = ((s0 & 0xE0) >> 5) | ((s1 & 0x03) << 3)
            out_idx += 1
            dest[out_idx] = (s1 & 0x7C) >> 2
            out_idx += 1
            dest[out_idx] = ((s1 & 0x80) >> 7) | ((s2 & 0x0F) << 1)
            out_idx += 1
            dest[out_idx] = ((s2 & 0xF0) >> 4) | ((s3 & 0x01) << 4)
            out_idx += 1
            dest[out_idx] = (s3 & 0x3E) >> 1
            out_idx += 1
            dest[out_idx] = ((s3 & 0xC0) >> 6) | ((s4 & 0x07) << 2)
            out_idx += 1
            dest[out_idx] = (s4 & 0xF8) >> 3
            out_idx += 1

            size -= 5

        if size == 4:
            s0 = src[in_idx]
            in_idx += 1
            s1 = src[in_idx]
            in_idx += 1
            s2 = src[in_idx]
            in_idx += 1
            s3 = src[in_idx]
            in_idx += 1

            dest[out_idx] = s0 & 0x1F
            out_idx += 1
            dest[out_idx] = ((s0 & 0xE0) >> 5) | ((s1 & 0x03) << 3)
            out_idx += 1
            dest[out_idx] = (s1 & 0x7C) >> 2
            out_idx += 1
            dest[out_idx] = ((s1 & 0x80) >> 7) | ((s2 & 0x0F) << 1)
            out_idx += 1
            dest[out_idx] = ((s2 & 0xF0) >> 4) | ((s3 & 0x01) << 4)
            out_idx += 1
            dest[out_idx] = (s3 & 0x3E) >> 1
            out_idx += 1

        elif size == 3:
            s0 = src[in_idx]
            in_idx += 1
            s1 = src[in_idx]
            in_idx += 1
            s2 = src[in_idx]
            in_idx += 1

            dest[out_idx] = s0 & 0x1F
            out_idx += 1
            dest[out_idx] = ((s0 & 0xE0) >> 5) | ((s1 & 0x03) << 3)
            out_idx += 1
            dest[out_idx] = (s1 & 0x7C) >> 2
            out_idx += 1
            dest[out_idx] = ((s1 & 0x80) >> 7) | ((s2 & 0x0F) << 1)
            out_idx += 1

        elif size == 2:
            s0 = src[in_idx]
            in_idx += 1
            s1 = src[in_idx]
            in_idx += 1

            dest[out_idx] = s0 & 0x1F
            out_idx += 1
            dest[out_idx] = ((s0 & 0xE0) >> 5) | ((s1 & 0x03) << 3)
            out_idx += 1
            dest[out_idx] = (s1 & 0x7C) >> 2
            out_idx += 1

        elif size == 1:
            s0 = src[in_idx]
            in_idx += 1

            dest[out_idx] = s0 & 0x1F
            out_idx += 1

        return dest

    def decompress(self, fp_stream: Bytes) -> UnpackedFP:
        self._unpack_header(fp_stream)
        offset = 4
        bits = self._unpack_int3_array(fp_stream[offset:])

        found_values = 0
        num_exceptional_bits = 0
        for index, bit in np.ndenumerate(bits):
            # index is a tuple (idx,)
            if bit == 0:
                found_values += 1
                if found_values == self._size:
                    bits.resize(index[0] + 1, refcheck=False)
                    break
            elif bit == self._kMaxNormalValue:
                num_exceptional_bits += 1

        if found_values != self._size:
            print_e(
                "Invalid fingerprint (too short, not enough input for normal bits),"
                f" {found_values}, {self._size}, {self._algorithm}"
            )
            raise DecompressFPError("Invalid fingerprint: found_values")

        offset += self._get_packed_int3_array_size(len(bits))

        if len(fp_stream) < (
            offset + self._get_packed_int5_array_size(num_exceptional_bits)
        ):
            print_e(
                "Invalid fingerprint (too short, not enough input for exceptional bits)"
            )
            raise DecompressFPError("Invalid fingerprint: len(fp_stream)")

        if num_exceptional_bits:
            exceptional_bits = self._unpack_int5_array(
                fp_stream[offset:], num_exceptional_bits
            )
            j = 0
            for i in range(len(bits)):
                if bits[i] == self._kMaxNormalValue:
                    bits[i] += exceptional_bits[j]
                    j += 1

        return UnpackedFP(self._size, self._algorithm, self._unpack_bits(bits))
