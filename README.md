# dbb-reader

A keyboard-driven terminal EPUB reader for a read-only local library. Python 3.11+.

Install with `uv sync` and launch with `uv run dbb-reader`. The library defaults to
`../Books` relative to this repository. Set it in the settings UI or user TOML config.
Books and personal reading data are never stored in this repository.

Run the tests with `uv run pytest`.
