"""Where the drawer lives on disk.

One rule, and everything else follows from it: `GAVETA_HOME` overrides everything.
That is what lets a test, a second profile, or a throwaway experiment run against a
directory that is not the user's real drawer — and it is why the test suite can
assert, structurally, that it never touched `~/.gaveta`.
"""

import os
from pathlib import Path

# The environment variable that overrides the default location, everywhere.
HOME_ENV_VAR = "GAVETA_HOME"

_DEFAULT_HOME = ".gaveta"
_DB_FILENAME = "gaveta.db"

# Owner-only. The drawer holds credential *references* from Stage 6 onward, and a
# world-readable default is not something a later stage can take back: directories
# created under the old mode keep it.
_HOME_MODE = 0o700


def gaveta_home() -> Path:
    """The drawer's directory. `GAVETA_HOME` if set, else `~/.gaveta`.

    An empty or whitespace-only `GAVETA_HOME` is treated as unset rather than as the
    current directory, which is what `Path("")` would otherwise mean.
    """
    override = os.environ.get(HOME_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / _DEFAULT_HOME


def db_path() -> Path:
    """The SQLite file. Deleting it resets the world, by design."""
    return gaveta_home() / _DB_FILENAME


def ensure_home() -> Path:
    """Create the drawer's directory if absent, and return it.

    Called on the write paths, not at import time: resolving a path must stay free of
    side effects so that tests and `--help` never touch the filesystem.
    """
    home = gaveta_home()
    home.mkdir(parents=True, exist_ok=True, mode=_HOME_MODE)
    return home
