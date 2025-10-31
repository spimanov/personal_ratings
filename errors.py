# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from enum import IntEnum


class ErrorCode(IntEnum):
    ERROR = 1
    CANCELLED = 2
    FINGERPRINT_ERROR = 3
    DB_LOCKED = 4
    DB_ERROR = 5


class Error:
    code: ErrorCode
    msg: str | None

    def __init__(self, code: ErrorCode, msg: str | None = None) -> None:
        self.code = code
        self.msg = msg
