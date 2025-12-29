# Copyright 2025 Sergey Pimanov <spimanov@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from pathlib import Path

from quodlibet import get_user_dir
from quodlibet.plugins import (
    PluginConfig,
    ConfProp,
    BoolConfProp,
)


class Config:

    default_db_path: str
    """ Default file name (path/filename) of the personal ratings DB (a local PRDB). """

    use_custom_db_path: BoolConfProp

    custom_db_path: ConfProp
    """ Custom file name (path/filename) of the personal ratings DB (a local PRDB). """

    db_path: ConfProp
    """ Actual file name (path/filename) of the personal ratings DB (a local PRDB). """

    sync_with_ext: BoolConfProp
    """ Synchronise the local PRDB with an external PRDB """

    ext_db_path: ConfProp
    """ File name (path/filename) of an external PRDB to sync with. """

    last_db_operation_uuid: ConfProp
    """ UUID of the latest operation, performed on the local DB. """

    last_ext_operation_uuid: ConfProp
    """ UUID of the latest operation, performed on the external DB. """

    sqlite_ext_lib: str
    """ Full path to the sqlite-phhammdist.so """

    _cfg: PluginConfig

    @classmethod
    def init(cls, prefix: str) -> None:
        cls._cfg = cfg = PluginConfig(prefix)
        # By default, the database file is located in the QL user configuration folder
        cls.default_db_path = str(Path(get_user_dir()) / "personal.db")

        cls.use_custom_db_path = BoolConfProp(cfg, "use_custom_db_path", False)
        cls.custom_db_path = ConfProp(cfg, "custom_db_path", cls.default_db_path)
        cls.db_path = ConfProp(cfg, "db_path", cls.default_db_path)

        cls.sync_with_ext = BoolConfProp(cfg, "sync_with_ext", False)
        cls.ext_db_path = ConfProp(cfg, "ext_db_path", "~/cloud/personal-ext.db")
        cls.last_db_operation_uuid = ConfProp(cfg, "last_db_operation_uuid", "")
        cls.last_ext_operation_uuid = ConfProp(cfg, "last_ext_operation_uuid", "")

        cls.sqlite_ext_lib = str(
            Path(__file__).resolve().parent / "sqlite-phhammdist" / "sqlite-phhammdist.so"
        )

    @classmethod
    def ConfigCheckButton(cls, label, name, default=False):
        return cls._cfg.ConfigCheckButton(label, name, default=default)


def get_config(prefix: str):
    """Get plugin configuration parameters.

    Args:
        prefix: str - a prefix of names of configuration parameters,
                      is used to avoid parameters names conflicts across plugins.
                      Has to be unique per plugin

    Returns:
        PersonalRatingsPluginConfig class object
    """
    Config.init(prefix)
    return Config()
