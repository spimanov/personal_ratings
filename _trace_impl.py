# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import errno
import os
import sys
import threading
import time

from senf import print_
from typing import Any

from quodlibet.util.logging import log as ql_log
from quodlibet.util.dprint import (
    START_TIME,
    Colorise,
    _should_write_to_file,
    _supports_ansi_escape_codes,
    frame_info,
    strip_color,
)


def print_thread_id() -> None:
    thread_id = threading.current_thread().ident
    thread_name = threading.current_thread().name
    print_d(f"Thread: {thread_name}, id: {thread_id}", None, 4)


def print_d(string: str, custom_context: str | None = None, context_level: int = 3):
    """Print debugging information."""
    _print_message(string, custom_context, "D", "green", "debug", context_level)


def print_w(string: str, context: str | None = None, context_level: int = 3):
    """Print warnings"""
    _print_message(string, context, "W", "yellow", "warnings", context_level)


def print_e(string: str, context: str | None = None, context_level: int = 3):
    """Print errors"""
    _print_message(string, context, "E", "red", "errors", context_level)


def _get_context(level: int = 0) -> str:
    context = frame_info(level)

    # strip the package name
    if context.count(".") > 1:
        context = context.split(".", 1)[-1]

    return context


def _print_message(
    string: str | Any,
    custom_context: str | None,
    prefix: str,
    color: str,
    logging_category: str,
    context_level: int,
    start_time: float = START_TIME,
):
    if not isinstance(string, str):
        string = str(string)

    context = _get_context(context_level)

    if custom_context:
        context = f"{context}({custom_context!r})"

    timestr = ("%08.3f" % (time.time() - start_time))[-9:]

    color_prefix = getattr(Colorise, color)(prefix)
    info = f"{color_prefix}: [{Colorise.magenta(timestr)}] {Colorise.green(context)}:"

    lines = string.splitlines()
    if len(lines) > 1:
        string = os.linesep.join([info] + [" " * 4 + line for line in lines])
    else:
        string = info + " " + lines[0]

    file_ = sys.stderr
    if _should_write_to_file(file_):
        if not _supports_ansi_escape_codes(file_):
            string = strip_color(string)
        try:
            print_(string, file=file_, flush=True)
        except OSError as e:
            if e.errno == errno.EIO:
                # When we are started in a terminal with --debug and the
                # terminal gets closed we lose stdio/err before we stop
                # printing debug message, resulting in EIO and aborting the
                # exit process -> Just ignore it.
                pass
            else:
                raise

    ql_log(strip_color(string), logging_category)
