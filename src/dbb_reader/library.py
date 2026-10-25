"""Cancelable metadata-only discovery; never read chapter bodies on the shelf."""
from dataclasses import dataclass
from functools import lru_cache
import unicodedata

from opencc import OpenCC
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
    is_directory: bool = False

    @property
    def supported(self) -> bool:
        return not self.is_directory and self.path.suffix.lower() == ".epub"


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


@lru_cache(maxsize=1)
def _converter() -> OpenCC:
    return OpenCC("t2s.json")


@lru_cache(maxsize=4096)
def normalize_search(text: str) -> str:
    """Canonical search form only; original metadata and files stay untouched."""
    return _converter().convert(unicodedata.normalize("NFKC", text)).casefold()


def filter_entries(entries: list[Entry], query: str = "", category: str = "") -> list[Entry]:
    terms = normalize_search(query).split() if query.strip() else []
    return [entry for entry in entries if (not category or entry.category == category)
            and (not terms or all(term in normalize_search(f"{entry.title} {entry.author}") for term in terms))]


def scan_directory(root: Path, directory: Path, cancel: Event | None = None, report=None) -> list[Entry]:
    """List real immediate children, including empty folders; never flatten the tree."""
    root = root.expanduser().resolve()
    directory = directory.expanduser().resolve()
    if not directory.is_relative_to(root):
        raise ValueError("無法離開書庫根目錄。")
    if not directory.is_dir():
        raise ValueError(f"找不到資料夾：{directory}；請開啟設定選擇書庫。")
    try:
        children = sorted(directory.iterdir(), key=lambda path: path.name.casefold())
        entries = []
        for path in children:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if path.is_symlink():
                continue
            if path.is_dir():
                entries.append(Entry(path, clean(path.name), "", "", is_directory=True))
            elif path.is_file() and path.suffix.lower() in (".epub", ".pdf"):
                entries.append(Entry(path, clean(path.stem), "", ""))
        entries.sort(key=lambda entry: (not entry.is_directory, entry.title.casefold()))
        if report:
            report(list(entries))
        for index, entry in enumerate(entries):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if entry.supported:
                try:
                    with ZipFile(entry.path) as archive:
                        pkg = package(archive)
                    entry = Entry(entry.path, pkg.title or entry.title, pkg.author, "")
                except Exception:
                    entry = Entry(entry.path, entry.title, "", "", error="EPUB 檔案無法讀取")
                entries[index] = entry
            if report and index % 10 == 9:
                report(list(entries))
        return entries
    except OSError as exc:
        raise ValueError(f"無法讀取資料夾：{exc}") from exc
