# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import time
import hashlib

from gi.repository import Gst
from gi.repository.Gio import Cancellable

from quodlibet.util import print_e


class GstElementError(Exception):
    def __init__(self, element_name: str) -> None:
        super().__init__("Error creating Gst.Element: " + element_name)


class AcousticFingerprint:
    """
    Calculate an acoustic fingerprint by using the chromaprint plugin

    https://gstreamer.freedesktop.org/documentation/coreelements/filesrc.html
    https://gstreamer.freedesktop.org/documentation/chromaprint/index.html

    cmd:
    gst-launch-1.0 -m filesrc location=/path/to/song.mp3 ! \
                              decodebin ! audioconvert ! chromaprint ! fakesink
    """

    def __init__(self):
        self._create_pipe()

    def _create_pipe(self):
        """Create Gstreamer pipeline"""

        self._pipeline = pipeline = Gst.Pipeline()

        # Source file
        self._filesrc = filesrc = Gst.ElementFactory.make("filesrc", None)

        if filesrc is None:
            raise GstElementError("filesrc")
        pipeline.add(filesrc)

        self._decoder = decoder = Gst.ElementFactory.make("decodebin", None)
        if decoder is None:
            raise GstElementError("decodebin")
        pipeline.add(decoder)
        filesrc.link(decoder)

        converter = Gst.ElementFactory.make("audioconvert", None)
        if converter is None:
            raise GstElementError("audioconvert")
        pipeline.add(converter)

        # Decodebin won't have pads from the beginning but will add some dynamically so
        # you can not do `decoder.link(converter)`. You can only link to them once
        # a pad is there.
        # https://gitlab.freedesktop.org/gstreamer/gstreamer-rs/-/blob/main/examples/src/bin/decodebin.rs

        # Simple function that is run when decodebin notifies that it has got audio data
        # to be processed. Use the get_static_pad call on the previously created
        # audioconverter element asking to a "sink" pad.
        def on_pad_added(decoder_, pad, *args):
            pad.link(converter.get_static_pad("sink"))

        self._dyn_pad_id = decoder.connect("pad-added", on_pad_added)

        chromaprint = Gst.ElementFactory.make("chromaprint", None)
        if chromaprint is None:
            raise GstElementError("chromaprint")
        pipeline.add(chromaprint)
        converter.link(chromaprint)

        fakesink = Gst.ElementFactory.make("fakesink", None)
        if fakesink is None:
            raise GstElementError("fakesink")
        pipeline.add(fakesink)
        chromaprint.link(fakesink)

        # bus
        self._bus = pipeline.get_bus()

    def close(self):
        if not self._pipeline:
            return
        if self._decoder is not None:
            self._decoder.disconnect(self._dyn_pad_id)
            self._decoder = None
        self._filesrc = None
        self._bus = None
        self._pipeline = None

    def get_chromaprint(
        self, cancellable: Cancellable, filename: str
    ) -> tuple[bool, str, int | None]:
        """Get gstreamer chromaprint for a file"""

        assert self._filesrc is not None
        assert self._pipeline is not None
        assert self._bus is not None

        self._filesrc.set_property("location", filename)

        start = time.perf_counter_ns()
        self._pipeline.set_state(Gst.State.PLAYING)

        # Duration (in nanoseconds) of the song, calculated by GStreamer (or did not)
        song_dur: int | None = None

        timeout = 1000  # Gst.CLOCK_TIME_NONE,
        while True:
            msg = self._bus.timed_pop_filtered(
                timeout,
                Gst.MessageType.TAG | Gst.MessageType.EOS | Gst.MessageType.ERROR,
            )

            error = None
            if msg is not None:
                if msg.type == Gst.MessageType.TAG:
                    # Get chromaprint tag value
                    tags = msg.parse_tag()
                    res, value = tags.get_string("chromaprint-fingerprint")
                    if res:
                        # The query_duration will only work once the pipeline is
                        # prerolled (i.e. reached PAUSED or PLAYING state). The
                        # application will receive an ASYNC_DONE message on the pipeline
                        # bus when that is the case.
                        # https://valadoc.org/gstreamer-1.0/Gst.Element.query_duration.html

                        res, duration = self._pipeline.query_duration(Gst.Format.TIME)
                        if res:
                            song_dur = duration
                        self._pipeline.set_state(Gst.State.NULL)
                        return (True, value, song_dur)
                elif msg.type == Gst.MessageType.EOS:
                    error = "EOS: no chromaprint calculated"
                elif msg.type == Gst.MessageType.ERROR:
                    err, debug = msg.parse_error()
                    print_e(
                        f"Error received from element {msg.src.get_name()}:"
                        f" {err.message} (debug: {debug})"
                    )
                    error = err.message

            if error:
                self._pipeline.set_state(Gst.State.NULL)
                return (False, error, song_dur)

            if cancellable.is_cancelled():
                self._pipeline.set_state(Gst.State.NULL)
                return (False, "Cancelled", song_dur)

            end = time.perf_counter_ns()
            if (end - start) >= 3 * Gst.SECOND:
                self._pipeline.set_state(Gst.State.NULL)
                return (False, "Timeout", song_dur)

    def calc_fingerprint(
        self, cancellable: Cancellable, filename: str, song_dur: float
    ) -> tuple[bool, str]:
        """
        Get hash1 of the file acoustic fingerprint
        Args:
            song_dur: float - duration of the song in seconds
        """

        res, val, gst_dur = self.get_chromaprint(cancellable, filename)

        if res:
            if gst_dur is None:
                song_dur = int(song_dur * Gst.SECOND)
            else:
                assert gst_dur != 0
                song_dur = gst_dur

            val += str(song_dur)
            sha1_hasher = hashlib.sha1()
            content = val.encode("utf-8")
            sha1_hasher.update(content)
            hash = sha1_hasher.hexdigest()
            return (True, hash)

        return (res, val)
