"""Per-book logical locations. Never persist text or titles."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .config import atomic_write, state_path


def book_id(path: Path) -> str:
    # Paths survive content updates. Moving/renaming a book intentionally creates a new identity.
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()


@dataclass
class Position:
    chapter: int = 0
    offset: int = 0
    progress: float = 0.0
    updated: str = ""
    href: str = ""


class State:
    def __init__(self, path: Path | None = None):
        self.path = path or state_path()
        self.positions: dict[str, Position] = {}
        self.warning: str | None = None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != 1 or not isinstance(data.get("books"), dict):
                raise ValueError("unsupported state format")
            for key, value in data["books"].items():
                p = Position(**value)
                if (type(p.chapter) is not int or p.chapter < 0 or type(p.offset) is not int
                        or p.offset < 0 or type(p.progress) not in (int, float)
                        or not 0 <= p.progress <= 1 or not isinstance(p.updated, str)
                        or not isinstance(p.href, str)):
                    raise ValueError("invalid reading position")
                self.positions[key] = p
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.positions = {}
            self.warning = f"Reading state could not be loaded: {exc}"

    def get(self, path: Path) -> Position:
        return self.positions.get(book_id(path), Position())

    def save(self, path: Path, chapter: int, offset: int, progress: float, href: str = "") -> None:
        self.positions[book_id(path)] = Position(chapter, offset, progress,
                                               datetime.now(timezone.utc).isoformat(), href)
        atomic_write(self.path, json.dumps({"version": 1, "books": {
            key: asdict(value) for key, value in self.positions.items()
        }}, ensure_ascii=False))
