# Installing the dev environment

Required reading:
[plugin development](https://quodlibet.readthedocs.io/en/latest/development/overview.html)

Install the `sqlite3` if not installed already

```bash
sudo apt install sqlite3
sudo apt-get install libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
     libgstreamer-plugins-good1.0-dev libgstreamer-plugins-bad1.0-dev \
     gstreamer1.0-plugins-ugly gstreamer1.0-libav gstreamer1.0-tools
```

```
sudo pacman -S gstreamer chromaprint
sudo pacman -S gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugins-ugly
```

Install the QL
```
git clone https://github.com/quodlibet/quodlibet.git

cd quodlibet
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install pycairo musicbrainzngs dbus-python PyGObject mutagen feedparser pygments
pip install numpy senf
pip install pygobject-stubs --config-settings=config=Gtk3,Gdk3
```

# To run QL in debug mode
```
python quodlibet.py --debug
```

# Configuring Pyright in your IDE

To support correct type hints in pyright, install typing stubs for PyGObject library
`pip install pygobject-stubs --config-settings=config=Gtk3,Gdk3`

More is [here](https://pypi.org/project/PyGObject-stubs/)

## Add pyright config file
Create a `pyrightconfig.json` in the quodlibet project folder  with:
```
{
    "useLibraryCodeForTypes": true,
    "reportMissingModuleSource": "none",
    "exclude": [
        ".venv/",
        ".venv_*/"
    ],
    "venvPath": ".",
    "venv": ".venv"
}
```
or edit the `pyproject.toml` correspondingly:
```
[tool.pyright]
exclude = [
   ".venv/",
   ".venv_*/",
]

venvPath = "."
venv = ".venv"
useLibraryCodeForTypes = true
```

# Delete fingerprints from the QLDB (in the Python console)
```
val = list(app.library.values())
fp = '~#fp_id'
for s in val:
    if fp in s:
        del s[fp]
```

Scanning library: 4032 songs...
To process: 4032 songs
--------------------------------------------------------------------------------
Done: processed: 4032, unprocessed: 0, skipped: 0, duration: 1996.20 sec
