# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""
To work with gstreamer, install it and set of plugins:

sudo pacman -S gstreamer chromaprint
sudo pacman -S gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugins-ugly
"""

import time

import gi
gi.require_version('PangoCairo', '1.0')
gi.require_version("Gst", "1.0")
# gi.require_version("Gtk", "3.0")

from gi.repository import Gst
from gi.repository.Gio import Cancellable

from typing import Optional, Type
from types import TracebackType

from quodlibet.util import print_e

from .fp_decompressor import FingerprintDecompressor
from .fingerprint import Fingerprint, hamming_distance, match_fingerprints


class FPCalcError(Exception):
    def __init__(self, msg: str) -> None:
        super().__init__(msg)


class FPGstElementError(FPCalcError):
    def __init__(self, element_name: str) -> None:
        super().__init__("Error creating Gst.Element: " + element_name)


class FPPipeError(FPCalcError):
    def __init__(self, msg: str) -> None:
        super().__init__("Error calculating FP: " + msg)


class FPCalcCancelled(FPCalcError):
    def __init__(self) -> None:
        super().__init__("Cancelled")


class FPCalcTimeout(FPCalcError):
    def __init__(self) -> None:
        super().__init__("Timeout")


class Pipeline:
    """ Configured Gstreamer pipline, ready to calculate acoustic fingerprints
        Pipeline example:
        gst-launch-1.0 -m filesrc location=/path/to/song.mp3 ! \
                              decodebin ! audioconvert ! chromaprint ! fakesink
    """

    _pipeline: Gst.Pipeline | None
    _filesrc: Gst.Element | None
    _decodebin: Gst.Element | None
    _dyn_pad_id: int

    _cancellable: Cancellable
    _calculating: bool

    def __init__(self, cancellable: Cancellable) -> None:
        """Create and pre-configure Gstreamer pipeline"""
        self._pipeline = None
        self._filesrc = None
        self._decodebin = None
        self._dyn_pad_id = 0
        self._cancellable = cancellable
        # Is pipeline processing?
        self._calculating = False

        # ================================================================================
        self._pipeline = Gst.Pipeline()
        # Source file
        self._filesrc = Gst.ElementFactory.make("filesrc", None)

        if self._filesrc is None:
            raise FPGstElementError("filesrc")
        self._pipeline.add(self._filesrc)

        self._decodebin = Gst.ElementFactory.make("decodebin", None)
        if self._decodebin is None:
            raise FPGstElementError("decodebin")
        self._pipeline.add(self._decodebin)
        self._filesrc.link(self._decodebin)

        converter = Gst.ElementFactory.make("audioconvert", None)
        if converter is None:
            raise FPGstElementError("audioconvert")
        self._pipeline.add(converter)

        # Decodebin won't have pads from the beginning but will add some dynamically so
        # you can not do `decodebin.link(converter)`. You can only link to them once
        # a pad is there.
        # https://gitlab.freedesktop.org/gstreamer/gstreamer-rs/-/blob/main/examples/src/bin/decodebin.rs

        # Simple function that is run when decodebin notifies that it has got audio data
        # to be processed. Use the get_static_pad call on the previously created
        # audioconverter element asking to a "sink" pad.
        def on_pad_added(decoder_: Gst.Element, pad: Gst.Pad, *args: str):
            cnv_pad = converter.get_static_pad("sink")
            if not cnv_pad:
                raise FPGstElementError("converter pad sink")

            pad.link(cnv_pad)

        self._dyn_pad_id = self._decodebin.connect("pad-added", on_pad_added)

        chromaprint = Gst.ElementFactory.make("chromaprint", None)
        if chromaprint is None:
            raise FPGstElementError("chromaprint")

        self._pipeline.add(chromaprint)
        converter.link(chromaprint)

        fakesink = Gst.ElementFactory.make("fakesink", None)
        if fakesink is None:
            raise FPGstElementError("fakesink")

        self._pipeline.add(fakesink)
        chromaprint.link(fakesink)

    def close(self) -> None:
        if not self._pipeline:
            return

        self._calculating = False

        if self._decodebin is not None:
            assert self._dyn_pad_id != 0
            self._decodebin.disconnect(self._dyn_pad_id)
            self._decodebin = None

        self._filesrc = None
        self._pipeline = None

    def _start_pipeline(self) -> None:
        assert self._pipeline

        ret = self._pipeline.set_state(Gst.State.PLAYING)

        if ret == Gst.StateChangeReturn.SUCCESS:
            return
        if ret == Gst.StateChangeReturn.ASYNC:
            # It is needed to work with a GLib MainLoop or manual bus polling
            return

        error = "Unable to set the pipeline to the PLAYING state."

        if ret == Gst.StateChangeReturn.FAILURE:
            bus = self._pipeline.get_bus()
            # Wait up to 5 seconds for an error message
            msg = bus.timed_pop_filtered(5 * Gst.SECOND, Gst.MessageType.ERROR)
            if msg:
                err, debug = msg.parse_error()
                # print debug trace
                print_e(debug)
                error = f"{msg.src.get_name()}: {err.message}"

        # It's good practice to set state to NULL on failure to clean up
        self._pipeline.set_state(Gst.State.NULL)
        raise FPPipeError(error)

    def calc(self, filename: str) -> str:
        """Calculate fingerprint - execute the pipeline for a file (with filename)
        @return base64 string value
        """

        assert self._pipeline is not None
        assert self._filesrc is not None

        assert not self._calculating

        # ================================================================================
        # Get the current pipeline state (pipeline state after creation: NULL)
        # Gst.CLOCK_TIME_NONE specifies an infinite timeout to wait for the state change
        ret, pipeline_state, _pending = self._pipeline.get_state(Gst.CLOCK_TIME_NONE)

        if ret == Gst.StateChangeReturn.SUCCESS:
            if pipeline_state != Gst.State.NULL:
                state = Gst.Element.state_get_name(pipeline_state)
                raise FPPipeError(f"Error getting pipline state: {state}")
        elif ret == Gst.StateChangeReturn.FAILURE:
            raise FPPipeError("Failed to get pipeline state.")
        else:
            state = Gst.Element.state_get_name(pipeline_state)
            raise FPPipeError(f"Error getting pipline state: {state}, ret: {ret}")

        # ================================================================================
        start_ts = time.perf_counter_ns()

        self._filesrc.set_property("location", filename)

        self._start_pipeline()

        self._calculating = True

        # https://github.com/gkralik/python-gst-tutorial/blob/master/basic-tutorial-4.py
        try:
            # listen to the bus
            bus = self._pipeline.get_bus()
            while True:
                types = Gst.MessageType.TAG | Gst.MessageType.EOS | Gst.MessageType.ERROR
                msg = bus.timed_pop_filtered(Gst.SECOND, types)
                # parse message
                if msg:
                    fp_base64 = self._handle_message(msg)
                    if fp_base64 is not None:
                        return fp_base64
                else:
                    # we got no message. this means the timeout expired
                    pass

                if (not self._calculating) or self._cancellable.is_cancelled():
                    self._calculating = False
                    raise FPCalcCancelled()

                end_ts = time.perf_counter_ns()
                if (end_ts - start_ts) >= 3 * Gst.SECOND:
                    self._calculating = False
                    raise FPCalcTimeout()
        finally:
            self._pipeline.set_state(Gst.State.NULL)

    def _get_duration(self) -> int:
        """Return duration (in nanoseconds) of the song, which was calculated by
        GStreamer (or was not...)
        """
        # The query_duration will only work once the pipeline is
        # prerolled (i.e. reached PAUSED or PLAYING state). The
        # application will receive an ASYNC_DONE message on the pipeline
        # bus when that is the case.
        # https://valadoc.org/gstreamer-1.0/Gst.Element.query_duration.html

        assert self._pipeline is not None

        res, duration = self._pipeline.query_duration(Gst.Format.TIME)
        if res:
            return duration
        else:
            raise FPPipeError("Unable to query duration.")

    def _handle_message(self, msg: Gst.Message) -> str | None:

        if msg.type == Gst.MessageType.TAG:
            # Get chromaprint tag value
            tags = msg.parse_tag()

            # get Fingerprint as a base64 encoded string
            res, fp_base64 = tags.get_string("chromaprint-fingerprint")
            if res:
                # duration = self._get_duration()
                self._calculating = False
                return fp_base64

        elif msg.type == Gst.MessageType.EOS:
            raise FPPipeError("EOS: no chromaprint calculated")
        elif msg.type == Gst.MessageType.ERROR:
            err, debug = msg.parse_error()
            print_e(
                f"Error received from element {msg.src.get_name()}:"
                f" {err.message} (debug: {debug})"
            )
            raise FPPipeError(err.message)

        return None


class FingerprintCalculator:
    """
    Calculate an acoustic fingerprint by using the chromaprint plugin.

    https://gstreamer.freedesktop.org/documentation/coreelements/filesrc.html
    https://gstreamer.freedesktop.org/documentation/chromaprint/index.html

    an example cmd:
    gst-launch-1.0 -m filesrc location=/path/to/song.mp3 ! \
                              decodebin ! audioconvert ! chromaprint ! fakesink
    """

    _pipeline: Pipeline | None

    def __init__(self, cancellable: Cancellable):
        self._pipeline = None
        self._cancellable = cancellable

        self._pipeline = Pipeline(cancellable)

    def open(self) -> Pipeline:
        if self._pipeline is None:
            self._pipeline = Pipeline(self._cancellable)

        return self._pipeline

    def close(self):
        if not self._pipeline:
            return
        self._pipeline.close()
        self._pipeline = None

    def __enter__(self):
        return self.open()

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> bool:
        self.close()
        return False  # Do not suppress exceptions

    def __del__(self):
        # This might be called much later, or not at all.
        # It calls _cleanup() safely due to the 'closed' flag.
        self.close()


if __name__ == "__main__":
    # gst-launch-1.0 -m filesrc location=~/Music/2listen/1.mp3 ! decodebin ! audioconvert ! chromaprint ! fakesink
    # To open in IDE:
    # PYTHONPATH="${HOME}/tools/quodlibet/quodlibet:$PYTHONPATH" vim fp_calculator.py
    # To run:
    # cd ..
    # PYTHONPATH="${HOME}/tools/quodlibet/quodlibet:$PYTHONPATH" python -m personal_ratings.fp_calculator
    import os

    try:
        Gst.init(None)
        cancellable = Cancellable()

        with FingerprintCalculator(cancellable) as pipe:
            # filename1 = os.path.expanduser("~/Music/2listen/1.mp3")
            # filename2 = os.path.expanduser("~/Music/2listen/2.mp3")
            filename1 = os.path.expanduser("/archive/music/eng rock/Dire Straits - Romeo And Juliet.mp3")
            filename2 = os.path.expanduser("/archive/music_tmp/Dire Straits - Romeo And Juliet.mp3")
            print("Start")
            fp1_base64 = pipe.calc(filename1)
            print("fp1 done")
            fp2_base64 = pipe.calc(filename2)
            print("fp2 done")

            dec = FingerprintDecompressor()
            fp1 = Fingerprint.from_base64(fp1_base64, dec)
            fp2 = Fingerprint.from_base64(fp2_base64, dec)

            print("f1 == f2 ?", fp1 == fp2)
            print("f2 == f1 ?", fp2 == fp1)

            h1 = fp1._hash
            h2 = fp2._hash
            print("hash 1:", h1)
            print("hash 2:", h2)

            print("dist 1-2:", hamming_distance(h1, h2))
            print("dist 2-1:", hamming_distance(h2, h1))

            equal_ratio1 = match_fingerprints(fp1._raw_fp, fp2._raw_fp)
            equal_ratio2 = match_fingerprints(fp2._raw_fp, fp1._raw_fp)

            print("ratio: 1-2:", equal_ratio1)
            print("ratio: 2-1:", equal_ratio2)

    except Exception as err:
        print_e(f"Unhandled exception: {err}")
