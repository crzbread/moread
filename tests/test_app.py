import asyncio
from dataclasses import replace
from pathlib import Path
from threading import Event
import time

import pytest
from textual.widgets import DataTable, Input, Select, Static

from dbb_reader.app import Contents, Loading, ReaderApp, Reading, Settings, Shelf
from dbb_reader.config import Config, load_config
from dbb_reader.epub import Cancelled
from dbb_reader.state import State


async def until(pilot, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("UI did not reach expected state")
        await pilot.pause(.02)
    await pilot.pause(.02)


def make_app(tmp_path, **config):
    return ReaderApp(Config(library=str(tmp_path), **config), config_file=tmp_path / "test.toml",
                     state=State(tmp_path / "test-state.json"))


async def ready(app, pilot):
    await until(pilot, lambda: isinstance(app.screen, Shelf) and not app.screen.scanning)


async def test_recent_reading_collects_books_across_directories(make_epub, tmp_path):
    (tmp_path / "一").mkdir()
    (tmp_path / "二").mkdir()
    first = make_epub("一/first.epub")
    second = make_epub("二/second.epub")
    make_epub("unread.epub")
    app = make_app(tmp_path)
    app.state.save(first, 0, 0, .2)
    app.state.save(second, 0, 0, .7)
    async with app.run_test(size=(80, 28)) as pilot:
        await ready(app, pilot)
        shelf = app.screen
        table = shelf.query_one(DataTable)
        assert table.coordinate_to_cell_key((0, 0)).row_key.value == "__recent__"
        table.move_cursor(row=0)
        await pilot.press("right")
        await until(pilot, lambda: not shelf.scanning)
        assert [entry.path for entry in shelf.filtered_entries] == [second, first]
        assert [entry.category for entry in shelf.filtered_entries] == ["二", "一"]
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, Reading))
        await pilot.press("escape", "left")
        await until(pilot, lambda: not shelf.scanning)
        assert not shelf.in_recent and shelf.selected_key() == "__recent__"


@pytest.mark.parametrize("screen", ["shelf", "search", "settings", "theme-select", "reading", "toc"])
async def test_global_panic_every_screen(make_epub, tmp_path, screen):
    make_epub()
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await ready(app, pilot)
        if screen == "search":
            await pilot.press("/")
            assert isinstance(app.focused, Input)
        elif screen in ("settings", "theme-select"):
            await pilot.press("s")
            await until(pilot, lambda: isinstance(app.screen, Settings))
            if screen == "theme-select":
                app.screen.query_one("#theme", Select).focus()
                await pilot.press("enter")
        elif screen in ("reading", "toc"):
            await pilot.press("enter")
            await until(pilot, lambda: isinstance(app.screen, Reading))
            if screen == "toc":
                await pilot.press("t")
                await until(pilot, lambda: isinstance(app.screen, Contents))
        await pilot.press("ctrl+d")
        await pilot.pause(.05)
        assert app._exit


@pytest.mark.parametrize("exit_key", ["ctrl+d", "q"])
async def test_panic_loading_and_cancel_does_not_wait(make_epub, tmp_path, monkeypatch, exit_key):
    make_epub()
    started, released = Event(), Event()
    def slow(path, cancel, report):
        started.set()
        while not cancel.wait(.01):
            pass
        released.set()
        raise Cancelled()
    monkeypatch.setattr("dbb_reader.app.load_book", slow)
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await ready(app, pilot)
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, Loading) and started.is_set())
        start = time.monotonic()
        await pilot.press(exit_key)
        await pilot.pause(.02)
        assert app._exit and time.monotonic() - start < 1
        assert released.wait(1)


async def test_folder_search_pdf_recovery_and_recent(make_epub, tmp_path):
    path = make_epub()
    category = tmp_path / "分類"
    category.mkdir()
    (category / "manual.pdf").write_bytes(b"unsupported")
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await ready(app, pilot)
        shelf = app.screen
        assert shelf.query_one(DataTable).row_count == 3
        assert shelf.filtered_entries[0].is_directory
        await pilot.press("right")
        await until(pilot, lambda: not shelf.scanning)
        assert shelf.current_directory == category
        assert len(shelf.filtered_entries) == 1
        await pilot.press("enter")
        assert app.screen is shelf
        await pilot.press("left")
        await until(pilot, lambda: not shelf.scanning)
        await pilot.press("/")
        shelf.query_one(Input).value = "作者"
        await pilot.pause()
        assert [e.path for e in shelf.filtered_entries] == [path]
        await pilot.press("enter", "enter")
        await until(pilot, lambda: isinstance(app.screen, Reading))
        await pilot.press("right", "escape")
        assert app.screen is shelf and app.state.get(path).updated
        assert shelf.filtered_entries[0].path == path


async def test_navigation_resize_resume_and_modes(make_epub, tmp_path):
    path = make_epub()
    app = make_app(tmp_path, reading_width=30)
    async with app.run_test(size=(60, 18)) as pilot:
        await ready(app, pilot)
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, Reading))
        reading = app.screen
        await pilot.press("right")
        assert reading.text_offset > 0
        saved = reading.text_offset
        await pilot.resize_terminal(100, 30)
        await pilot.pause()
        assert reading.text_offset == saved
        assert State(app.state.path).get(path).offset == saved
        await pilot.press("escape", "enter")
        await until(pilot, lambda: isinstance(app.screen, Reading))
        assert app.screen.text_offset == saved
        await pilot.press("n")
        assert app.screen.chapter == 1 and app.screen.text_offset == 0
        await pilot.press("t")
        await until(pilot, lambda: isinstance(app.screen, Contents))
        await pilot.press("home", "enter")
        assert app.screen.chapter == 0 and app.screen.text_offset > 0
        assert app.config.mode == "page"
        reading = app.screen
        reading.goto(0, 0)
        await pilot.press("down")
        one_line = reading.text_offset
        reading.goto(0, 0)
        await pilot.press("pagedown")
        assert (reading.chapter, reading.text_offset) > (0, one_line)
        await pilot.press("n", "end")
        assert app.state.get(path).progress == 1.0


async def test_interactive_config_and_custom_panic(make_epub, tmp_path):
    make_epub()
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await ready(app, pilot)
        await pilot.press("s")
        await until(pilot, lambda: isinstance(app.screen, Settings))
        app.screen.query_one("#width", Input).value = "0"
        app.screen.query_one("#save").focus()
        await pilot.press("enter")
        assert isinstance(app.screen, Settings)
        await until(pilot, lambda: not app.screen.query_one("#save").has_class("-active"))
        app.screen.query_one("#width", Input).value = "42"
        app.screen.query_one("#mode", Select).value = "scroll"
        app.screen.query_one("#panic-key", Input).value = "ctrl+x"
        # Save may be below the viewport in a small terminal; invoke button action via focus.
        app.screen.query_one("#save").focus()
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, Shelf))
        assert load_config(app.config_file)[0] == app.config
        assert app.config.reading_width == 42 and app.config.mode == "scroll"
        await pilot.press("/")
        await pilot.press("ctrl+d")
        assert not app._exit
        await pilot.press("ctrl+x")
        await pilot.pause(.02)
        assert app._exit


async def test_missing_and_empty_libraries_recover_in_settings(tmp_path):
    app = make_app(tmp_path / "absent")
    async with app.run_test() as pilot:
        await ready(app, pilot)
        assert "找不到" in app.screen.error
        await pilot.press("s")
        await until(pilot, lambda: isinstance(app.screen, Settings))
        empty = tmp_path / "empty"
        empty.mkdir()
        app.screen.query_one("#library", Input).value = str(empty)
        app.screen.query_one("#save").focus()
        await pilot.press("enter")
        await ready(app, pilot)
        assert not app.screen.entries and not app.screen.error


async def test_deleted_book_open_error_is_recoverable(make_epub, tmp_path):
    path = make_epub()
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await ready(app, pilot)
        path.unlink()
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, Shelf) and "load" not in app.jobs)
        assert not app._exit


async def test_directory_arrows_parent_empty_breadcrumbs_and_root_boundary(make_epub, tmp_path):
    make_epub()
    top = tmp_path / "A分類"
    nested = top / "空資料夾"
    nested.mkdir(parents=True)
    (tmp_path / "B分類").mkdir()
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await ready(app, pilot)
        shelf = app.screen
        assert len(shelf.filtered_entries) == 3
        assert [e.is_directory for e in shelf.filtered_entries] == [True, True, False]
        await pilot.press("down")
        assert shelf.selected_key() == str(tmp_path / "B分類")
        await pilot.press("up", "right")
        await until(pilot, lambda: not shelf.scanning)
        assert shelf.current_directory == top
        assert "A分類" in str(shelf.query_one("#shelf-path", Static).content)
        assert shelf.query_one(DataTable).row_count == 2
        assert shelf.selected_key() == str(nested)
        await pilot.press("enter")
        await until(pilot, lambda: not shelf.scanning)
        assert shelf.current_directory == nested and not shelf.filtered_entries
        assert shelf.selected_key() == "__parent__"
        assert "空的" in str(shelf.query_one("#shelf-status", Static).content)
        await pilot.press("enter")
        await until(pilot, lambda: not shelf.scanning)
        assert shelf.current_directory == top and shelf.selected_key() == str(nested)
        await pilot.press("backspace")
        await until(pilot, lambda: not shelf.scanning)
        assert shelf.current_directory == tmp_path and shelf.selected_key() == str(top)
        await pilot.press("left", "backspace", "escape")
        assert shelf.current_directory == tmp_path


async def test_search_editing_arrows_backspace_escape_then_parent(tmp_path):
    child = tmp_path / "分類"
    (child / "心理學與閱讀").mkdir(parents=True)
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await ready(app, pilot)
        await pilot.press("right")
        shelf = app.screen
        await until(pilot, lambda: not shelf.scanning)
        await pilot.press("/")
        search = shelf.query_one(Input)
        search.value = "心理学"
        await pilot.pause()
        assert len(shelf.filtered_entries) == 1
        search.cursor_position = len(search.value)
        await pilot.press("left", "right", "backspace")
        assert search.value == "心理" and shelf.current_directory == child
        await pilot.press("escape")
        assert search.value == "" and shelf.current_directory == child
        assert app.focused is shelf.query_one(DataTable)
        await pilot.press("/")
        await pilot.press("escape")
        await until(pilot, lambda: not shelf.scanning)
        assert shelf.current_directory == tmp_path


@pytest.mark.parametrize("route", ["f2", "button"])
async def test_settings_shortcut_from_input_preserves_text_editing(tmp_path, route):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await ready(app, pilot)
        if route == "f2":
            await pilot.press("/", "f2")
        else:
            await pilot.press("tab", "enter")
        await until(pilot, lambda: isinstance(app.screen, Settings))
        field = app.screen.query_one("#library", Input)
        field.focus()
        field.value = "abcdef"
        await pilot.pause()
        assert app.focused is field
        field.cursor_position = 3
        await pilot.press("left", "backspace", "right")
        assert field.value == "acdef" and field.cursor_position == 2
        assert isinstance(app.screen, Settings)
        await pilot.press("ctrl+d")
        await pilot.pause(.02)
        assert app._exit


@pytest.mark.parametrize("width", [40, 60, 80, 120])
async def test_progress_visible_without_horizontal_overflow(make_epub, tmp_path, width):
    path = make_epub()
    app = make_app(tmp_path)
    app.state.save(path, 0, 20, .375)
    async with app.run_test(size=(width, 24)) as pilot:
        await ready(app, pilot)
        table = app.screen.query_one(DataTable)
        assert table.virtual_size.width <= table.content_size.width
        assert table.get_cell_at((1, 1)) == "37.5%"
        await pilot.resize_terminal(max(40, width - 20), 24)
        await pilot.pause()
        assert table.virtual_size.width <= table.content_size.width
        assert table.get_cell_at((1, 1)) == "37.5%"


async def test_global_panic_during_directory_scan(tmp_path, monkeypatch):
    entered = Event()
    def slow(root, directory, cancel, report):
        entered.set()
        cancel.wait(5)
        raise Cancelled()
    monkeypatch.setattr("dbb_reader.app.scan_directory", slow)
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await until(pilot, entered.is_set)
        await pilot.press("/", "ctrl+d")
        await pilot.pause(.02)
        assert app._exit


@pytest.mark.parametrize("format", ["epub", "pdf"])
async def test_right_never_opens_books_enter_still_opens(make_epub, tmp_path, format):
    if format == "epub":
        make_epub()
    else:
        (tmp_path / "manual.pdf").write_bytes(b"unsupported")
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await ready(app, pilot)
        shelf = app.screen
        await pilot.press("right", "right", "right")
        assert app.screen is shelf and "load" not in app.jobs
        await pilot.press("enter")
        if format == "epub":
            await until(pilot, lambda: isinstance(app.screen, Reading))
            await pilot.press("escape")
        assert app.screen is shelf


@pytest.mark.parametrize("screen", ["shelf", "reading", "toc", "settings-button"])
async def test_q_exits_outside_inputs(make_epub, tmp_path, screen):
    make_epub()
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await ready(app, pilot)
        if screen in ("reading", "toc"):
            await pilot.press("enter")
            await until(pilot, lambda: isinstance(app.screen, Reading))
            if screen == "toc":
                await pilot.press("t")
        elif screen == "settings-button":
            await pilot.press("f2")
            app.screen.query_one("#save").focus()
        await pilot.press("q")
        await pilot.pause(.02)
        assert app._exit


async def test_q_is_text_in_search_and_settings_and_safe_in_dropdown(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await ready(app, pilot)
        await pilot.press("/", "q")
        assert app.screen.query_one(Input).value == "q" and not app._exit
        await pilot.press("f2")
        field = app.screen.query_one("#library", Input)
        field.focus()
        await pilot.pause()
        await pilot.press("q")
        assert field.value.endswith("q") and not app._exit
        select = app.screen.query_one("#theme", Select)
        select.focus()
        await pilot.pause()
        await pilot.press("q")
        assert not app._exit
        await pilot.press("enter")
        assert select.expanded
        await pilot.press("q")
        assert select.expanded and not app._exit
        await pilot.press("ctrl+d")
        await pilot.pause(.02)
        assert app._exit


def test_footer_descriptions_are_traditional_chinese():
    from textual.binding import Binding
    for screen in (Shelf, Loading, Contents, Reading, Settings, ReaderApp):
        for binding in screen.BINDINGS:
            description = binding.description if isinstance(binding, Binding) else binding[2]
            assert any('\u4e00' <= char <= '\u9fff' for char in description), description


@pytest.mark.parametrize("size,book_height,folder_height", [((40, 18), 1, 1), ((74, 24), 2, 2), ((80, 24), 2, 2),
                                                          ((100, 30), 3, 2)])
async def test_adaptive_shelf_spacing_preserves_rows_progress_and_metadata(make_epub, tmp_path, size, book_height, folder_height):
    path = make_epub()
    (tmp_path / "分類").mkdir()
    for i in range(12):
        make_epub(f"book-{i:02}.epub")
    app = make_app(tmp_path)
    app.state.save(path, 0, 20, .375)
    async with app.run_test(size=size) as pilot:
        await ready(app, pilot)
        shelf = app.screen
        table = shelf.query_one(DataTable)
        assert table.virtual_size.width <= table.content_size.width
        assert table.region.x >= (1 if size[0] < 60 else 2)
        assert table.get_row_height(str(tmp_path / "分類")) == folder_height
        assert table.get_row_height(str(path)) == book_height
        name = table.get_cell(str(path), list(table.columns)[0])
        assert name.plain.startswith("真正書名") and "作者" in name.plain
        assert name.get_style_at_offset(app.console, 0).bold
        author_style = name.get_style_at_offset(app.console, name.plain.index("作者"))
        assert author_style.dim and not author_style.bold
        assert table.get_cell(str(path), list(table.columns)[1]) == "37.5%"
        available = table.content_size.height - table.header_height
        assert available >= (10 if size[1] == 18 else 15)
        from wcwidth import wcswidth
        help_widget = shelf.query_one("#shelf-help", Static)
        assert all(wcswidth(line) <= help_widget.content_size.width
                   for line in help_widget.content.plain.splitlines())
        await pilot.press("/")
        assert all(wcswidth(line) <= help_widget.content_size.width
                   for line in help_widget.content.plain.splitlines())
        await pilot.press("enter")
        if book_height > 1:
            assert name.plain.splitlines()[1].strip() == "作者"
        # Every entry is reachable with arrows even in the minimum-height viewport.
        await pilot.press(*(["down"] * table.row_count))
        assert table.cursor_row == table.row_count - 1 and table.scroll_y > 0
        assert "→ 不開書" not in str(shelf.query_one("#shelf-help", Static).content)
        await pilot.resize_terminal(40, 18)
        await pilot.pause()
        assert table.get_row_height(str(path)) == 1
        assert table.virtual_size.width <= table.content_size.width
        assert table.get_cell(str(path), list(table.columns)[1]) == "37.5%"


async def test_existing_reading_and_loading_status_use_chinese_and_configured_panic(make_epub, tmp_path, monkeypatch):
    make_epub()
    app = make_app(tmp_path, panic_key="ctrl+x")
    async with app.run_test() as pilot:
        await ready(app, pilot)
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, Reading))
        status = str(app.screen.query_one("#progress", Static).content)
        help_text = str(app.screen.query_one("#reading-help", Static).content)
        assert "章" in status and "空白 翻一頁" in help_text and "Ctrl+X" in help_text and "離開" in help_text
        assert "Chapter" not in status and "exit" not in status and "page" not in status
        await pilot.press("escape")
        def slow(path, cancel, report):
            cancel.wait(5)
            raise Cancelled()
        monkeypatch.setattr("dbb_reader.app.load_book", slow)
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, Loading))
        status = str(app.screen.query_one("#load-status", Static).content)
        assert "Ctrl+X" in status and "Ctrl+D" not in status and "離開" in status
        await pilot.press("ctrl+x")
