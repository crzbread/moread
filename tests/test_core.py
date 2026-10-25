from dataclasses import replace
from pathlib import Path
from threading import Event
from zipfile import ZipFile

import pytest
from wcwidth import wcswidth

from dbb_reader.config import Config, load_config, save_config
from dbb_reader.epub import BookError, Cancelled, load_book
from dbb_reader.layout import line_at, wrap
from dbb_reader.library import scan_library, filter_entries
from dbb_reader.state import State


def test_spine_order_metadata_toc_and_text(make_epub):
    book = load_book(make_epub())
    assert book.title == "真正書名" and book.author == "作者"
    assert [ch.href for ch in book.chapters] == ["OPS/second.xhtml", "OPS/first.xhtml"]
    assert "ignore" not in book.chapters[0].text
    assert book.toc[0].title == "目錄 第二章"
    assert book.chapters[0].text[book.toc[0].offset:].startswith("春眠")
    first_size = len(book.chapters[0].text)
    assert book.progress(1, 0) == first_size / book.total
    assert book.progress(1, len(book.chapters[1].text)) == 1


def test_state_independent_and_logical_resume(make_epub, tmp_path):
    first, second = make_epub(), make_epub("two.epub")
    state = State(tmp_path / "reading.json")
    book = load_book(first)
    state.save(first, 1, 153, book.progress(1, 153), book.chapters[1].href)
    state.save(second, 0, 7, 0.1)
    restored = State(state.path)
    assert restored.get(first).offset == 153 and restored.get(second).offset == 7
    assert "真正書名" not in state.path.read_text()
    for width in [20, 35, 80]:
        lines = wrap(book.chapters[1].text, width)
        line = lines[line_at(lines, restored.get(first).offset)]
        assert line.start <= 153 <= line.end
    assert book.clamp(9999, 999999, "OPS/first.xhtml") == (1, len(book.chapters[1].text))


def test_cjk_graphemes_and_source_offsets():
    text = "中文abc e\u0301👨‍👩‍👧‍👦\n下一段\n\n終"
    lines = wrap(text, 6)
    assert all(wcswidth(line.text) <= 6 for line in lines)
    assert ''.join(text[line.start:line.end] for line in lines) == text
    assert any("e\u0301" in line.text for line in lines)
    assert any("👨‍👩‍👧‍👦" in line.text for line in lines)
    assert "\n" not in ''.join(line.text for line in lines)


def test_config_roundtrip_and_invalid(tmp_path):
    path = tmp_path / "settings.toml"
    config = Config(library='/a/中文"book', mode="scroll", panic_key="ctrl+x")
    save_config(config, path)
    assert load_config(path) == (config, None)
    for content in ['mode = "wrong"', 'reading_width = true', 'panic_key = "ctrl+m"', 'unknown = 1', 'bad [']:
        path.write_text(content)
        defaults, warning = load_config(path)
        assert defaults == Config() and warning
    for key in ["ctrl+i", "escape", "ctrl+j", "x"]:
        with pytest.raises(ValueError):
            replace(config, panic_key=key).validate()


def test_library_pdf_invalid_search_and_categories(make_epub, tmp_path):
    make_epub()
    category = tmp_path / "小說"
    category.mkdir()
    (category / "sample.pdf").write_bytes(b"not rendered")
    (tmp_path / "broken.epub").write_bytes(b"broken")
    entries = scan_library(tmp_path)
    assert len(entries) == 3
    assert filter_entries(entries, "真正 作者")[0].title == "真正書名"
    assert not filter_entries(entries, "unmatched")
    assert filter_entries(entries, category="小說")[0].supported is False
    assert next(e for e in entries if e.path.name == "broken.epub").error
    with pytest.raises(ValueError, match="does not exist"):
        scan_library(tmp_path / "missing")


def test_cancel_and_malformed(make_epub, tmp_path):
    event = Event()
    event.set()
    with pytest.raises(Cancelled):
        load_book(make_epub(), event)
    with pytest.raises(BookError):
        load_book(tmp_path / "missing.epub")
    state_path = tmp_path / "bad-state.json"
    state_path.write_text('{"version":1,"books":{"x":{"chapter":-1}}}')
    assert State(state_path).warning
