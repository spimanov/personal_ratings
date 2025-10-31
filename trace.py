# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from quodlibet import const

DEBUG = True and const.DEBUG

if DEBUG:
    from ._trace_impl import print_e, print_w, print_d, print_thread_id
else:
    from quodlibet.util import print_e, print_w, print_d

    def print_thread_id() -> None:
        pass


__all__ = ["print_e", "print_w", "print_d", "print_thread_id"]
