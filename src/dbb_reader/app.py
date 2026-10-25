"""Keyboard-only Textual interface. Disk/EPUB work never runs in the UI loop."""
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event, Thread
from typing import Callable

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Input, Label, Select, Static

from .config import Config, config_path, save_config
from .epub import Book, Cancelled, load_book
from .layout import line_at, wrap
from .library import Entry, filter_entries, scan_directory
from .state import State


class ShelfTable(DataTable):
    """Directory keys apply only to the listing, never to editable inputs."""
    BINDINGS = [Binding("right", "open", "開啟", show=False),
                Binding("left,backspace", "parent", "上層", show=False)]

    def action_open(self):
        self.screen.action_open()

    def action_parent(self):
        self.screen.action_parent()


class Shelf(Screen):
    BINDINGS = [Binding("/", "search", "搜尋"),
                Binding("f2", "settings", "設定", priority=True),
                Binding("s", "settings", "設定", show=False),
                Binding("r", "recent", "最近閱讀", show=False),
                Binding("f5", "reload", "重新整理", show=False),
                Binding("escape", "escape", "清除／上層", priority=True, show=False)]

    def compose(self) -> ComposeResult:
        with Horizontal(id="shelf-header"):
            yield Static("書櫃 · dbb-reader", id="shelf-title")
            yield Button("設定 F2", id="shelf-settings")
        yield Static("", id="shelf-path")
        yield Label("搜尋目前資料夾：書名、作者或資料夾名稱（不含子資料夾）", id="search-label")
        yield Input(placeholder="按 / 搜尋；Enter 回到清單", id="search")
        yield Static("讀取中…", id="shelf-status")
        yield ShelfTable(id="books", cursor_type="row", zebra_stripes=True)
        yield Static("", id="shelf-help")

    def on_mount(self):
        self.recent_first = False
        self.entries: list[Entry] = []
        self.filtered_entries: list[Entry] = []
        self.error = ""
        self.scanning = True
        self.selection_history: dict[Path, str] = {}
        self.preferred_key = None
        self.root = Path(self.reader.config.library).expanduser().resolve()
        self.current_directory = self.root
        self.query_one(DataTable).focus()
        self.navigate(self.root)

    @property
    def reader(self) -> "ReaderApp":
        return self.app  # type: ignore[return-value]

    def selected_key(self):
        table = self.query_one(DataTable)
        if table.row_count:
            return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return None

    def navigate(self, directory: Path, select: str | None = None):
        if not directory.is_relative_to(self.root):
            return
        if selected := self.selected_key():
            self.selection_history[self.current_directory] = selected
        self.current_directory = directory
        self.entries = []
        self.preferred_key = select or self.selection_history.get(directory) or "__default__"
        self.scanning, self.error = True, ""
        self.query_one(DataTable).clear()
        self.query_one("#search", Input).value = ""
        self.query_one(DataTable).focus()
        self.refresh_books()
        self.reader.start_scan(self)

    def set_entries(self, entries: list[Entry], complete=False, error=""):
        self.entries, self.scanning, self.error = entries, not complete, error
        self.refresh_books()

    def refresh_books(self):
        table = self.query_one(DataTable)
        selected = self.preferred_key or self.selected_key()
        query = self.query_one("#search", Input).value
        self.filtered_entries = filter_entries(self.entries, query)
        self.filtered_entries.sort(key=lambda entry: (entry.title.casefold(), str(entry.path)))
        if self.recent_first:
            self.filtered_entries.sort(key=lambda entry: self.reader.state.get(entry.path).updated, reverse=True)
        self.filtered_entries.sort(key=lambda entry: not entry.is_directory)
        # Explicit widths reserve progress and type. Long CJK titles are truncated, never
        # allowed to push these columns into a horizontal scrolling region.
        table.clear(columns=True)
        width = max(24, self.size.width)
        type_width = 10 if width >= 50 else 4
        name_width = max(1, width - type_width - 7 - 8)
        table.add_column("名稱／作者", width=name_width)
        table.add_column("進度", width=7)
        table.add_column("類型", width=type_width)
        keys = []
        if self.current_directory != self.root:
            table.add_row(Text("← .. 上層資料夾"), "", "", key="__parent__")
            keys.append("__parent__")
        for entry in self.filtered_entries:
            position = self.reader.state.get(entry.path)
            name = ("▸ " if entry.is_directory else "") + entry.title
            if entry.author:
                name += " · " + entry.author
            kind = "資料夾" if entry.is_directory else ("損壞" if entry.error else
                    ("EPUB" if entry.supported else ("PDF 不支援" if width >= 50 else "PDF")))
            progress = f"{position.progress:.1%}" if entry.supported else "—"
            key = str(entry.path)
            table.add_row(Text(name, no_wrap=True, overflow="ellipsis"), progress, kind, key=key)
            keys.append(key)
        default_index = 1 if self.current_directory != self.root and self.filtered_entries else 0
        if selected in keys:
            table.move_cursor(row=keys.index(selected))
            self.preferred_key = None
        else:
            table.move_cursor(row=default_index)
            if self.filtered_entries:
                self.preferred_key = None
        relative = self.current_directory.relative_to(self.root)
        breadcrumb = self.root.name + (" / " + " / ".join(relative.parts) if relative.parts else "（書庫根目錄）")
        self.query_one("#shelf-path", Static).update(Text("目前：" + breadcrumb, no_wrap=True, overflow="ellipsis"))
        folder_count = sum(entry.is_directory for entry in self.filtered_entries)
        book_count = len(self.filtered_entries) - folder_count
        message = self.error or ("讀取中… " if self.scanning else "") + f"{folder_count} 個資料夾 · {book_count} 本書"
        if query:
            message += " · 僅搜尋目前資料夾"
        elif not self.entries and not self.scanning and not self.error:
            message += " · 此資料夾是空的"
        if self.recent_first:
            message += " · 書籍依最近閱讀排序"
        self.query_one("#shelf-status", Static).update(Text(message))
        self.update_help()

    def on_resize(self):
        if hasattr(self, "entries"):
            self.call_after_refresh(self.refresh_books)

    def on_descendant_focus(self):
        if hasattr(self, "entries"):
            self.update_help()

    def update_help(self):
        if self.app.focused is self.query_one("#search", Input):
            help_text = "←→ 游標 · Backspace 刪字 · Enter 回清單 · Esc 清除／上層"
        else:
            help_text = "↑↓ 選擇 · → / Enter 開啟 · ← / Backspace 上層 · / 搜尋"
        help_text += f"\nEsc 清除搜尋再回上層 · r 最近閱讀 · F5 重新整理 · F2 設定 · {self.reader.config.panic_key.replace('ctrl+', 'Ctrl+').upper().replace('CTRL', 'Ctrl')} 離開"
        self.query_one("#shelf-help", Static).update(Text(help_text))

    @on(Input.Changed, "#search")
    def filter_changed(self):
        if hasattr(self, "entries"):
            self.refresh_books()

    @on(Input.Submitted, "#search")
    def search_submitted(self):
        self.query_one(DataTable).focus()

    @on(DataTable.RowSelected, "#books")
    def open_selected(self):
        self.action_open()

    def action_open(self):
        selected = self.selected_key()
        if selected == "__parent__":
            self.action_parent()
            return
        entry = next((entry for entry in self.entries if str(entry.path) == selected), None)
        if entry is None:
            return
        if entry.is_directory:
            self.navigate(entry.path)
        elif not entry.supported:
            self.notify("此版本不支援 PDF 閱讀，請選擇 EPUB。", severity="warning")
        elif entry.error:
            self.notify(entry.error + "；請檢查檔案，按 F5 重新整理。", severity="error")
        else:
            self.reader.open_entry(entry)

    def action_parent(self):
        if self.current_directory != self.root:
            self.navigate(self.current_directory.parent, select=str(self.current_directory))

    def action_escape(self):
        search = self.query_one("#search", Input)
        if search.value:
            search.value = ""
            self.query_one(DataTable).focus()
        else:
            self.action_parent()
            self.query_one(DataTable).focus()

    def action_search(self):
        self.query_one(Input).focus()

    @on(Button.Pressed, "#shelf-settings")
    def action_settings(self):
        self.reader.push_screen(Settings())

    def action_recent(self):
        self.recent_first = not self.recent_first
        self.refresh_books()

    def action_reload(self):
        self.scanning = True
        self.error = ""
        self.refresh_books()
        self.reader.start_scan(self)

class Settings(Screen):
    BINDINGS = [("escape", "cancel", "取消")]

    def compose(self) -> ComposeResult:
        config = self.app.config
        yield Static("設定 · Tab 切換欄位", classes="heading")
        with VerticalScroll(id="settings-fields"):
            yield Label("書庫資料夾")
            yield Input(config.library, id="library")
            yield Label("閱讀模式（實驗功能）")
            yield Select([("分頁", "page"), ("捲動", "scroll")], value=config.mode, allow_blank=False, id="mode")
            yield Label("閱讀寬度（20–240 終端格）")
            yield Input(str(config.reading_width), id="width", type="integer")
            yield Label("佈景主題")
            yield Select([(t, t) for t in ("textual-dark", "textual-light", "nord", "gruvbox")],
                         value=config.theme, allow_blank=False, id="theme")
            yield Label("全域離開鍵（ctrl+字母；h、i、j、m 除外）")
            yield Input(config.panic_key, id="panic-key")
            yield Static(Text(f"設定檔：{self.app.config_file}"))
            yield Static("", id="settings-error")
            with Horizontal(classes="buttons"):
                yield Button("儲存", id="save", variant="primary")
                yield Button("取消", id="cancel")
        yield Footer()

    @on(Button.Pressed, "#save")
    def save(self):
        try:
            config = Config(
                library=str(Path(self.query_one("#library", Input).value).expanduser().resolve()),
                mode=str(self.query_one("#mode", Select).value),
                reading_width=int(self.query_one("#width", Input).value),
                theme=str(self.query_one("#theme", Select).value),
                panic_key=self.query_one("#panic-key", Input).value.strip().lower(),
            ).validate()
            if not self.query_one("#library", Input).value.strip():
                raise ValueError("請輸入書庫路徑。")
            if not Path(config.library).is_dir():
                raise ValueError("找不到此資料夾，請檢查書庫路徑。")
            save_config(config, self.app.config_file)
        except (ValueError, OSError) as exc:
            self.query_one("#settings-error", Static).update(Text(str(exc)))
            return
        self.app.apply_config(config)
        self.app.pop_screen()

    @on(Button.Pressed, "#cancel")
    def action_cancel(self):
        self.app.pop_screen()


class Loading(Screen):
    BINDINGS = [("escape", "cancel", "Cancel opening")]

    def compose(self):
        yield Static("Opening EPUB…", classes="heading")
        yield Static("Building full-book text progress. The panic key remains active.", id="load-status")
        yield Footer()

    def action_cancel(self):
        self.app.cancel_job("load")
        self.app.pop_screen()


class Contents(Screen):
    BINDINGS = [("escape", "cancel", "Back")]

    def __init__(self, reading: "Reading"):
        super().__init__()
        self.reading = reading

    def compose(self):
        yield Static("Table of contents · Enter to jump", classes="heading")
        yield DataTable(id="toc", cursor_type="row")
        yield Footer()

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_column("Chapter")
        for index, item in enumerate(self.reading.book.toc):
            table.add_row(Text("  " * min(12, item.depth) + item.title), key=str(index))
        current = max((i for i, item in enumerate(self.reading.book.toc)
                       if (item.chapter, item.offset) <= (self.reading.chapter, self.reading.text_offset)), default=0)
        table.move_cursor(row=current)
        table.focus()

    @on(DataTable.RowSelected)
    def selected(self, event):
        item = self.reading.book.toc[int(event.row_key.value)]
        self.reading.goto(item.chapter, item.offset)
        self.app.pop_screen()

    def action_cancel(self):
        self.app.pop_screen()


class Reading(Screen):
    BINDINGS = [
        ("space,pagedown,right", "move(1, True)", "Next page"),
        ("pageup,left", "move(-1, True)", "Previous page"),
        ("down,j", "move(1, False)", "Down"), ("up,k", "move(-1, False)", "Up"),
        ("n", "chapter(1)", "Next chapter"), ("p", "chapter(-1)", "Previous chapter"),
        ("t", "toc", "Contents"), ("s", "settings", "Settings"),
        ("home", "start", "Chapter start"), ("end", "end", "Chapter end"),
        ("escape,b", "back", "Bookshelf"),
    ]

    def __init__(self, entry: Entry, book: Book):
        super().__init__()
        self.entry, self.book = entry, book
        self.chapter = self.text_offset = 0
        self._layout_key = None
        self.lines = []
        self._save_warning = False

    def compose(self):
        yield Static("", id="reading-heading", classes="heading")
        with Vertical(id="reading-area"):
            yield Static("", id="text", markup=False)
        yield Static("", id="progress")
        yield Footer()

    def on_mount(self):
        position = self.app.state.get(self.entry.path)
        self.chapter, self.text_offset = self.book.clamp(position.chapter, position.offset, position.href)
        self.call_after_refresh(self.render_page)

    def on_screen_resume(self):
        if self.is_mounted:
            self.call_after_refresh(self.render_page)

    def on_resize(self):
        if self.is_mounted:
            self.call_after_refresh(self.render_page)

    @property
    def page_height(self):
        return max(1, self.query_one("#reading-area").content_size.height)

    def layout_lines(self):
        area = self.query_one("#reading-area")
        width = max(2, min(self.app.config.reading_width, area.content_size.width))
        key = (self.chapter, width)
        if key != self._layout_key:
            self.lines = wrap(self.book.chapters[self.chapter].text, width)
            self._layout_key = key
        self.query_one("#text").styles.width = width
        return self.lines

    def render_page(self):
        lines = self.layout_lines()
        index = line_at(lines, self.text_offset)
        text = self.book.chapters[self.chapter].text
        if self.text_offset >= len(text):
            index = max(0, len(lines) - self.page_height)
        visible = lines[index:index + self.page_height]
        self.query_one("#text", Static).update(Text("\n".join(line.text for line in visible)))
        self.query_one("#reading-heading", Static).update(Text(
            f"{self.book.title} · {self.book.chapters[self.chapter].title}"))
        progress = self.book.progress(self.chapter, self.text_offset)
        cells = min(24, max(4, self.size.width // 5))
        filled = round(progress * cells)
        self.query_one("#progress", Static).update(Text(
            f"{'━' * filled}{'─' * (cells - filled)} {progress:.1%} · Chapter {self.chapter + 1}/{len(self.book.chapters)} · {self.app.config.mode} · {self.app.config.panic_key} exit"))

    def goto(self, chapter, offset):
        self.chapter, self.text_offset = self.book.clamp(chapter, offset)
        self.render_page()
        self.save_position()

    def save_position(self):
        try:
            self.app.state.save(self.entry.path, self.chapter, self.text_offset,
                                self.book.progress(self.chapter, self.text_offset),
                                self.book.chapters[self.chapter].href)
        except OSError as exc:
            if not self._save_warning:
                self.notify(f"Cannot save reading position: {exc}", severity="error", timeout=10)
                self._save_warning = True

    def action_move(self, direction: int, page: bool):
        lines = self.layout_lines()
        index = line_at(lines, self.text_offset)
        step = self.page_height if page else 1
        if direction > 0:
            next_index = index + step
            if next_index < len(lines) and self.text_offset < len(self.book.chapters[self.chapter].text):
                self.goto(self.chapter, lines[next_index].start)
            elif self.chapter < len(self.book.chapters) - 1:
                self.goto(self.chapter + 1, 0)
            else:
                self.goto(self.chapter, len(self.book.chapters[self.chapter].text))
        else:
            if index > 0:
                self.goto(self.chapter, lines[max(0, index - step)].start)
            elif self.chapter > 0:
                self.chapter -= 1
                lines = self.layout_lines()
                self.goto(self.chapter, lines[max(0, len(lines) - step)].start)

    def action_chapter(self, direction):
        self.goto(self.chapter + direction, 0)

    def action_start(self):
        self.goto(self.chapter, 0)

    def action_end(self):
        self.goto(self.chapter, len(self.book.chapters[self.chapter].text))

    def action_toc(self):
        self.app.push_screen(Contents(self))

    def action_settings(self):
        self.app.push_screen(Settings())

    def action_back(self):
        self.save_position()
        self.app.pop_screen()
        self.app.screen.refresh_books()


class ReaderApp(App):
    TITLE = "dbb-reader"
    ENABLE_COMMAND_PALETTE = False
    SUB_TITLE = ""
    BINDINGS = [Binding("ctrl+d", "panic", "離開", priority=True, id="panic"),
                Binding("ctrl+c", "panic", "Exit", show=False, priority=True)]
    CSS = """
    Screen { layout: vertical; }
    .heading { height: 2; text-style: bold; padding: 0 1; }
    #shelf-header { height: 3; }
    #shelf-title { width: 1fr; padding: 1 1; text-style: bold; }
    #shelf-settings { width: 18; min-width: 16; }
    #shelf-path, #shelf-status { height: 1; padding: 0 1; }
    #search-label { height: auto; padding: 0 1; }
    #shelf-help { height: auto; padding: 0 1; color: $text-muted; }
    #books { overflow-x: hidden; }
    #books, #toc { height: 1fr; }
    #settings-fields { padding: 0 2; height: 1fr; }
    #settings-fields Label { margin-top: 1; }
    #settings-error { color: $error; height: auto; }
    .buttons { height: 3; margin-top: 1; }
    .buttons Button { margin-right: 2; }
    #reading-area { height: 1fr; align-horizontal: center; overflow: hidden; }
    #text { height: auto; }
    #progress { height: 1; }
    """

    def __init__(self, config: Config | None = None, *, config_file: Path | None = None,
                 state: State | None = None, warning: str | None = None):
        super().__init__()
        self.config = (config or Config()).validate()
        self.config_file = config_file or config_path()
        self.state = state or State()
        self.warning = warning
        self.jobs: dict[str, Event] = {}
        self.results: SimpleQueue = SimpleQueue()
        self.theme = self.config.theme
        self.set_keymap({"panic": self.config.panic_key})

    def run(self, **kwargs):
        kwargs["mouse"] = False
        return super().run(**kwargs)

    def on_mount(self):
        self.set_interval(0.05, self.drain_results)
        self.push_screen(Shelf())
        for warning in (self.warning, self.state.warning):
            if warning:
                self.notify(warning + " · 請開啟設定檢查。", severity="warning", timeout=15)

    def apply_config(self, config):
        old = self.config
        self.config = config
        self.theme = config.theme
        self.set_keymap({"panic": config.panic_key})
        if old.library != config.library:
            shelf = next(screen for screen in self.screen_stack if isinstance(screen, Shelf))
            shelf.root = Path(config.library).expanduser().resolve()
            shelf.navigate(shelf.root)
        else:
            for screen in self.screen_stack:
                if isinstance(screen, Shelf) and screen.is_mounted:
                    screen.update_help()

    def cancel_job(self, group):
        if event := self.jobs.pop(group, None):
            event.set()

    def background(self, group: str, task: Callable, done: Callable, progress: Callable | None = None):
        self.cancel_job(group)
        cancel = Event()
        self.jobs[group] = cancel
        def emit(kind, value):
            if not cancel.is_set():
                self.results.put((group, cancel, kind, value, done, progress))
        def run():
            try:
                result = task(cancel, lambda value: emit("progress", value))
                emit("done", (result, None))
            except Cancelled:
                pass
            except Exception as exc:
                emit("done", (None, str(exc)))
        Thread(target=run, name=f"reader-{group}", daemon=True).start()

    def drain_results(self):
        for _ in range(20):
            try:
                group, cancel, kind, value, done, progress = self.results.get_nowait()
            except Empty:
                return
            if self.jobs.get(group) is not cancel or cancel.is_set():
                continue
            if kind == "progress":
                if progress:
                    progress(value)
            else:
                self.jobs.pop(group, None)
                done(*value)

    def start_scan(self, shelf: Shelf):
        root, directory = shelf.root, shelf.current_directory
        self.background("scan", lambda cancel, report: scan_directory(root, directory, cancel, report),
                        lambda entries, error: shelf.set_entries(entries or [], complete=True, error=error or ""),
                        lambda entries: shelf.set_entries(entries))

    def open_entry(self, entry):
        loading = Loading()
        self.push_screen(loading)
        def finished(book, error):
            if self.screen is not loading:
                return
            self.pop_screen()
            if error:
                self.notify(error + " · Return to the shelf and press F5 to rescan.", severity="error", timeout=12)
            else:
                self.push_screen(Reading(entry, book))
        def report(value):
            if loading.is_mounted:
                loading.query_one("#load-status", Static).update(
                    f"Reading spine {value[0]}/{value[1]}… · {self.config.panic_key} exits immediately")
        self.background("load", lambda cancel, progress: load_book(entry.path, cancel,
                        lambda count, total: progress((count, total))), finished, report)

    def action_panic(self):
        # Positions are already durable after every move. Never wait for extraction to finish.
        for cancel in self.jobs.values():
            cancel.set()
        self.jobs.clear()
        self.exit()

    def on_unmount(self):
        for cancel in self.jobs.values():
            cancel.set()
