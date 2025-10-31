# Installing the dev environment

Required reading:
[plugin development](https://quodlibet.readthedocs.io/en/latest/development/overview.html)

Install the `sqlite3` if not installed already
```bash
sudo apt install sqlite3
```

Install the QL
```
git clone https://github.com/quodlibet/quodlibet.git

cd quodlibet
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install pycairo musicbrainzngs dbus-python PyGObject mutagen feedparser
pip install pygobject-stubs --config-settings=config=Gtk3,Gdk3
```

# To run QL in debug mode
```
python quodlibet.py --debug
```

# Configuring Pyright in your IDE

To support correct type hints in pyright, install typing stubs for PyGObject library
`pip install pygobject-stubs`

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

