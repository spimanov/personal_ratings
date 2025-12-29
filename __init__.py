# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.


import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk

from typing import override

from quodlibet import _
from quodlibet.plugins.events import EventPlugin
from quodlibet.qltk import Icons
from quodlibet.util.songwrapper import SongWrapper

from .preferences import Preferences
from .config import get_config
from ._plugin_impl import PluginImpl


class PersonalRatingsPlugin(EventPlugin):
    VERSION = "1.0"
    PLUGIN_ID = "personalratingsdb"
    PLUGIN_NAME = _("Personal Ratings DB")
    PLUGIN_DESC = _("Syncs ratings and song statistics with a personal local DB.")
    PLUGIN_ICON = Icons.DOCUMENT_SAVE

    def __init__(self) -> None:
        self._impl: PluginImpl | None = None
        self._config = get_config(self.PLUGIN_ID)

    @override
    def enabled(self) -> None:
        assert self._impl is None
        self._impl = PluginImpl(self._config)

    @override
    def disabled(self) -> None:
        assert self._impl is not None

        self._impl.stop()
        del self._impl
        self._impl = None

    @override
    def plugin_on_added(self, songs: list[SongWrapper]) -> None:
        # quodlibet/plugins/events.py:131
        assert self._impl is not None
        self._impl.on_added(songs)

    @override
    def plugin_on_changed(self, songs: list[SongWrapper]) -> None:
        # quodlibet/plugins/events.py:131
        assert self._impl is not None
        self._impl.on_changed(songs)

    def PluginPreferences(self, parent: Gtk.Box) -> Gtk.Widget:
        self._preferences = Preferences(self._config)
        return self._preferences.create(parent)
