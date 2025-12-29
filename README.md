# Quod Libet plugin: Personal Ratings DB

This is a plugin for [Quod Libet](https://quodlibet.readthedocs.io/en/latest/) - the
excellent music management program.

## Overview
If you move songs files across directories instead of creating playlists, you lose
song's playback statistics, because QL uses the file path as a key in its DB (QLDB). The
purpose of the plugin is to try to keep songs stats. To do so, the plugin calculates songs
fingerprints and uses them as keys in its own database - PRDB. Note: the plugin changes
your QLDB and adds a new tag "~fingerprint" to each song in the DB, please do make
backups.

It is also possible to sync the local PRDB with an external one, if you use QL on several
desktops.

TODO: To add details and to extend the description.

## Getting Started
To install the plugin, clone the repository to `~/.config/quodlibet/plugins`.
```
git clone https://github.com/spimanov/personal_ratings
```

[link](https://quodlibet.readthedocs.io/en/latest/development/plugins.html)


# Warning.
The plugin is not tested properly. Please do make backups of your QLDB, before you install
the plugin.

# Plans
The original purpose of the plugin - is to sync songs ratings between two instances of QL
- on a home and a work computers. I do not have any plans to develop the plugin but
  bug-fixing.
