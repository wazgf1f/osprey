# Contributing

Thanks for taking a look. Osprey is a small project, so the process is short.

## Scope

Bug fixes, performance work, docs, tests and new backends are welcome.

Not welcome: features whose purpose is to defeat attendance, watch-time,
assessment or exam checks, or to evade anti-cheat in competitive multiplayer.
Those pull requests will be closed.

## Development setup

```bat
git clone https://github.com/wazgf1f/osprey.git
cd osprey
python -m venv .venv
.venv\Scripts\activate
pip install -e .
pip install pytest ruff
```

## Tests

The suite uses `unittest` so it runs with no extra dependency:

```bat
python -m unittest discover -s tests -t . -v
```

pytest works too:

```bat
pytest
```

Before opening a pull request, also run the live check on Windows:

```bat
python tools/selftest.py
```

That one catches capture regressions the unit tests cannot see.

## Style

- Python 3.9 compatible syntax, `from __future__ import annotations`.
- Line length 100, enforced by ruff (`ruff check src tests`).
- Type hints on public functions.
- No new runtime dependencies without a good reason; NumPy and Pillow are the
  only required ones.

## Pull requests

- One logical change per PR.
- Include a test that fails before the change.
- Describe the behaviour change, not just the diff.
- If you touch the matcher, include numbers: score accuracy and timing before
  and after.

## Commit messages

Conventional Commits style, for example:

```
feat(vision): add masked matching
fix(input): release keys when a task raises
docs: explain coordinate spaces
```

## Adding a task example

Examples live in `examples/` and should run without arguments on a fresh
checkout. Dry run by default; never send input unless the user passes
`--live`.
