"""Read ZIP/OPF metadata and spine text without extracting files to disk."""
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
import posixpath
import re
from threading import Event
from urllib.parse import unquote, urldefrag
from zipfile import ZipFile

from defusedxml import ElementTree as ET


class BookError(ValueError):
    pass


class Cancelled(Exception):
    pass


def clean(text: str) -> str:
    # No terminal escapes or control sequences from untrusted metadata/content.
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", text)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def target(base: str, href: str) -> tuple[str, str]:
    path, fragment = urldefrag(href)
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(path))), unquote(fragment)


@dataclass
class Package:
    title: str
    author: str
    spine: list[str]
    manifest: dict[str, tuple[str, str, str]]
    opf: str


def package(archive: ZipFile) -> Package:
    container = ET.fromstring(archive.read("META-INF/container.xml"))
    roots = [e.attrib["full-path"] for e in container.iter() if local(e.tag) == "rootfile"]
    if not roots:
        raise BookError("EPUB has no package document.")
    opf = roots[0]
    root = ET.fromstring(archive.read(opf))
    def metadata(name: str) -> str:
        return clean("; ".join("".join(e.itertext()).strip() for e in root.iter()
                               if local(e.tag) == name)).strip()
    manifest = {e.attrib["id"]: (target(opf, e.attrib["href"])[0],
                e.attrib.get("media-type", ""), e.attrib.get("properties", ""))
                for e in root.iter() if local(e.tag) == "item"}
    spine = [manifest[e.attrib["idref"]][0] for e in root.iter()
             if local(e.tag) == "itemref" and e.attrib.get("linear", "yes") != "no"]
    return Package(metadata("title"), metadata("creator"), spine, manifest, opf)


BLOCKS = set("p div section article h1 h2 h3 h4 h5 h6 li ul ol blockquote pre tr br hr dt dd figure figcaption".split())


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.size = 0
        self.skip = 0
        self.anchors: dict[str, int] = {}
        self.heading = ""
        self.in_heading = False

    def add(self, value: str) -> None:
        self.parts.append(value)
        self.size += len(value)

    def boundary(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.add("\n")

    def handle_starttag(self, tag, attrs):
        tag = tag.split(":")[-1]
        if tag in ("script", "style", "head"):
            self.skip += 1
        if self.skip:
            return
        if tag in BLOCKS:
            self.boundary()
        for key, value in attrs:
            if key in ("id", "name") and value:
                self.anchors[value] = self.size
        if tag in ("h1", "h2", "h3") and not self.heading:
            self.in_heading = True

    def handle_endtag(self, tag):
        tag = tag.split(":")[-1]
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        if self.skip:
            return
        if tag in BLOCKS:
            self.boundary()
        if tag in ("h1", "h2", "h3"):
            self.in_heading = False

    def handle_data(self, data):
        if not self.skip:
            value = re.sub(r"\s+", " ", clean(data))
            if not value.strip() and (not self.parts or self.parts[-1].endswith("\n")):
                return
            if self.in_heading:
                self.heading += value
            self.add(value)

    def result(self) -> str:
        return "".join(self.parts)


@dataclass
class Chapter:
    href: str
    title: str
    text: str
    anchors: dict[str, int] = field(default_factory=dict)


@dataclass
class TocEntry:
    title: str
    chapter: int
    offset: int = 0
    depth: int = 0


@dataclass
class Book:
    title: str
    author: str
    chapters: list[Chapter]
    toc: list[TocEntry]
    starts: list[int] = field(init=False)
    total: int = field(init=False)

    def __post_init__(self):
        self.starts = []
        self.total = 0
        for chapter in self.chapters:
            self.starts.append(self.total)
            self.total += len(chapter.text)

    def clamp(self, chapter: int, offset: int, href: str = "") -> tuple[int, int]:
        if href:
            chapter = next((i for i, ch in enumerate(self.chapters) if ch.href == href), chapter)
        chapter = min(max(0, chapter), len(self.chapters) - 1)
        return chapter, min(max(0, offset), len(self.chapters[chapter].text))

    def progress(self, chapter: int, offset: int) -> float:
        chapter, offset = self.clamp(chapter, offset)
        return (self.starts[chapter] + offset) / self.total if self.total else 0.0


def read_toc(archive: ZipFile, pkg: Package, chapters: list[Chapter]) -> list[TocEntry]:
    indexes = {ch.href: i for i, ch in enumerate(chapters)}
    result: list[TocEntry] = []
    def add(label: str, base: str, href: str, depth: int):
        path, anchor = target(base, href)
        if path in indexes:
            index = indexes[path]
            result.append(TocEntry(clean(label).strip() or chapters[index].title, index,
                                   chapters[index].anchors.get(anchor, 0), depth))
    navs = [path for path, _, props in pkg.manifest.values() if "nav" in props.split()]
    ncxs = [path for path, media, _ in pkg.manifest.values() if media == "application/x-dtbncx+xml"]
    try:
        if navs:
            base = navs[0]
            root = ET.fromstring(archive.read(base))
            nav = next((e for e in root.iter() if local(e.tag) == "nav" and
                        any("toc" in v.split() for k, v in e.attrib.items() if local(k) == "type")), None)
            def walk(node, depth=0):
                if local(node.tag) == "a" and "href" in node.attrib:
                    add("".join(node.itertext()), base, node.attrib["href"], max(0, depth - 1))
                for child in node:
                    walk(child, depth + (local(child.tag) == "ol"))
            if nav is not None:
                walk(nav)
        if not result and ncxs:
            base = ncxs[0]
            root = ET.fromstring(archive.read(base))
            def walk_ncx(node, depth=0):
                if local(node.tag) == "navPoint":
                    label = next(("".join(e.itertext()) for e in node if local(e.tag) == "navLabel"), "")
                    content = next((e for e in node if local(e.tag) == "content"), None)
                    if content is not None:
                        add(label, base, content.attrib.get("src", ""), depth)
                    depth += 1
                for child in node:
                    walk_ncx(child, depth)
            walk_ncx(root)
    except Exception:
        # Malformed optional navigation must not prevent reading a valid spine.
        result = []
    return result or [TocEntry(ch.title, i) for i, ch in enumerate(chapters)]


def load_book(path: Path, cancel: Event | None = None, report=None) -> Book:
    try:
        with ZipFile(path) as archive:
            pkg = package(archive)
            chapters = []
            for index, href in enumerate(pkg.spine):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                parser = TextParser()
                # Feed in bounded chunks so cancellation can interrupt a large single spine item.
                with archive.open(href) as stream:
                    import codecs
                    decoder = codecs.getincrementaldecoder("utf-8")("replace")
                    while chunk := stream.read(65536):
                        if cancel is not None and cancel.is_set():
                            raise Cancelled()
                        parser.feed(decoder.decode(chunk))
                    parser.feed(decoder.decode(b"", final=True))
                parser.close()
                chapters.append(Chapter(href, clean(parser.heading.strip()) or f"Chapter {index + 1}",
                                        parser.result(), parser.anchors))
                if report and (index % 20 == 0 or index == len(pkg.spine) - 1):
                    report(index + 1, len(pkg.spine))
            if not chapters or not any(ch.text.strip() for ch in chapters):
                raise BookError("No readable text found. This EPUB may contain only images or DRM.")
            return Book(pkg.title or path.stem, pkg.author, chapters, read_toc(archive, pkg, chapters))
    except Cancelled:
        raise
    except BookError:
        raise
    except Exception as exc:
        raise BookError(f"Cannot read EPUB: {type(exc).__name__}: {exc}") from exc
