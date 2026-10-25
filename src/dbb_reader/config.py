"""Validated user configuration, stored outside the library and checkout."""
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib

from platformdirs import user_config_path, user_state_path


DEFAULT_LIBRARY = Path.home() / "Documents" / "Self" / "Books"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".reader-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def config_path() -> Path:
    return user_config_path("dbb-reader") / "config.toml"


def state_path() -> Path:
    return user_state_path("dbb-reader") / "state.json"


@dataclass(frozen=True)
class Config:
    library: str = str(DEFAULT_LIBRARY)
    mode: str = "page"
    reading_width: int = 80
    theme: str = "textual-dark"
    panic_key: str = "ctrl+d"

    def validate(self) -> "Config":
        if not isinstance(self.library, str) or not self.library.strip():
            raise ValueError("Library must be a nonempty path.")
        if self.mode not in ("page", "scroll"):
            raise ValueError("Mode must be page or scroll.")
        if type(self.reading_width) is not int or not 20 <= self.reading_width <= 240:
            raise ValueError("Reading width must be an integer from 20 to 240.")
        if self.theme not in ("textual-dark", "textual-light", "nord", "gruvbox"):
            raise ValueError("Theme must be textual-dark, textual-light, nord or gruvbox.")
        # Restrict to unambiguous terminal chords. Ctrl+H/I/M/J are Backspace/Tab/Enter/newline.
        if not isinstance(self.panic_key, str) or not re.fullmatch(r"ctrl\+[a-gkln-z]", self.panic_key):
            raise ValueError("Panic key must be ctrl+letter (except h, i, j, m).")
        return self


def load_config(path: Path | None = None) -> tuple[Config, str | None]:
    path = path or config_path()
    try:
        values = tomllib.loads(path.read_text(encoding="utf-8"))
        unknown = set(values) - set(Config.__dataclass_fields__)
        if unknown:
            raise ValueError("Unknown setting: " + ", ".join(sorted(unknown)))
        return replace(Config(), **values).validate(), None
    except FileNotFoundError:
        return Config(), None
    except (OSError, ValueError, TypeError) as exc:
        return Config(), f"Config could not be loaded; using defaults. {exc}"


def save_config(config: Config, path: Path | None = None) -> None:
    config.validate()
    lines = [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in vars(config).items()]
    atomic_write(path or config_path(), "# dbb-reader settings\n" + "\n".join(lines) + "\n")
