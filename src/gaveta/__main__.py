"""`python -m gaveta`, the same entry point as the `gaveta` and `gv` console scripts.

Worth having for its own sake, and load-bearing for the cross-process persistence tests:
`sys.executable -m gaveta` is unambiguous under `uv run`, tox, and CI, where the console
script's location on `PATH` is not.
"""

from gaveta.cli import main

raise SystemExit(main())
