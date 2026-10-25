"""Cancelable metadata-only discovery; never read chapter bodies on the shelf."""
from dataclasses import dataclass
import os
from pathlib import Path
from threading import Event
from zipfile import ZipFile

from .epub import clean, package, Cancelled


@dataclass
class Entry:
    path: Path
    title: str
    author: str
    category: str
    error: str = ""

    @property
    def supported(self) -> bool:
        return self.path.suffix.lower() == ".epub"


def scan_library(root: Path, cancel: Event | None = None, report=None) -> list[Entry]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Library folder does not exist: {root}")
    entries = []
    errors = []
    def onerror(exc):
        errors.append(str(exc))
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        dirs.sort(key=str.casefold)
        for filename in sorted(files, key=str.casefold):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            path = Path(directory) / filename
            if path.suffix.lower() not in (".epub", ".pdf"):
                continue
            # Do not follow file symlinks out of the configured library.
            if not path.resolve().is_relative_to(root):
                continue
            category = str(path.parent.relative_to(root))
            if category == ".":
                category = "Uncategorized"
            entry = Entry(path, clean(path.stem), "", clean(category))
            if entry.supported:
                try:
                    with ZipFile(path) as archive:
                        pkg = package(archive)
                    entry.title = pkg.title or entry.title
                    entry.author = pkg.author
                except Exception as exc:
                    entry.error = f"Invalid EPUB: {type(exc).__name__}"
            entries.append(entry)
            if report and len(entries) % 10 == 0:
                report(list(entries))
    if errors:
        raise ValueError("Some library folders could not be read: " + "; ".join(errors))
    return entries


def filter_entries(entries: list[Entry], query: str = "", category: str = "") -> list[Entry]:
    terms = query.casefold().split()
    return [entry for entry in entries if (not category or entry.category == category)
            and all(term in f"{entry.title} {entry.author}".casefold() for term in terms)]
