"""Suite-wide isolation: no test ever touches the real drawer.

`GAVETA_HOME` is redirected to a per-test tmp directory *autouse*, so isolation is
structural rather than something each test has to remember. The guard tests in
`test_paths.py` assert this fixture is doing its job, and a negative control there
proves the guard can actually fail.
"""

from pathlib import Path

import pytest

from gaveta.paths import HOME_ENV_VAR


@pytest.fixture(autouse=True)
def gaveta_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point `GAVETA_HOME` at a fresh directory for every test, without exception.

    Autouse and unconditional. A test that wants the default resolution back must
    `monkeypatch.delenv` it explicitly, which makes reading the real home a visible
    act rather than an oversight.
    """
    home = tmp_path / "gaveta-home"
    monkeypatch.setenv(HOME_ENV_VAR, str(home))
    return home
