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
    BINDINGS = [Binding("right", "enter_directory", "進入資料夾", show=False),
                Binding("left,backspace", "parent", "上層", show=False)]

    def action_enter_directory(self):
        self.screen.action_open(directories_only=True)

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
            yield Static(Text.assemble(("書櫃", "bold"), ("  dbb-reader", "dim")), id="shelf-title")
            yield Button("設定 F2", id="shelf-settings")
        yield Static("", id="shelf-path")
        with Horizontal(id="shelf-search"):
            yield Static("/", id="search-label")
            yield Input(placeholder="搜尋此資料夾 · 書名／作者", id="search", compact=True)
        yield Static("讀取中…", id="shelf-status")
        yield ShelfTable(id="books", cursor_type="row", cursor_foreground_priority="renderable")
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
        self.set_class(self.size.height < 24, "compact")
        self.set_class(self.size.width < 60, "narrow")
        self.roomy_rows = self.size.height >= 24
        gutter = 1 if self.size.width < 60 else 2
        # Reserve both screen gutters, cell padding, and a scrollbar, including
        # the first frame after a terminal resize before CSS has reflowed.
        width = max(24, self.size.width - 2 * gutter)
        type_width = 10 if width >= 60 else 4
        name_width = max(1, width - type_width - 7 - 8)
        table.add_column("書名／作者" if self.roomy_rows else "名稱", width=name_width)
        table.add_column("進度", width=7)
        table.add_column("類型", width=type_width)
        keys = []
        if self.current_directory != self.root:
            table.add_row(Text("← .. 上層資料夾", style="dim"), "", "", key="__parent__",
                          height=2 if self.roomy_rows else 1)
            keys.append("__parent__")
        for entry in self.filtered_entries:
            position = self.reader.state.get(entry.path)
            name = Text(("▸ " if entry.is_directory else "") + entry.title,
                        style="bold", no_wrap=True, overflow="ellipsis")
            if self.roomy_rows:
                name.append("\n")
                if entry.author:
                    name.append("  " + entry.author, style="not bold dim")
            elif entry.author:
                name.append("  · " + entry.author, style="not bold dim")
            kind = "" if entry.is_directory else ("損壞" if entry.error else
                    ("EPUB" if entry.supported else ("PDF 不支援" if type_width >= 10 else "PDF")))
            progress = f"{position.progress:.1%}" if entry.supported else ""
            key = str(entry.path)
            row_height = (2 if entry.is_directory else (3 if self.size.height >= 28 else 2)) if self.roomy_rows else 1
            table.add_row(name, progress, Text(kind, style="dim"), key=key, height=row_height)
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
        breadcrumb = Text(self.root.name, style="dim", no_wrap=True, overflow="ellipsis")
        if relative.parts:
            for index, part in enumerate(relative.parts):
                breadcrumb.append(" / ", style="dim")
                breadcrumb.append(part, style="bold" if index == len(relative.parts) - 1 else "dim")
        else:
            breadcrumb.append(" /", style="bold")
        self.query_one("#shelf-path", Static).update(breadcrumb)
        folder_count = sum(entry.is_directory for entry in self.filtered_entries)
        book_count = len(self.filtered_entries) - folder_count
        message = self.error or ("讀取中… " if self.scanning else "") + f"{folder_count} 個資料夾 · {book_count} 本書"
        if query:
            message += " · 此資料夾的搜尋結果"
        elif not self.entries and not self.scanning and not self.error:
            message += " · 此資料夾是空的"
        if self.recent_first:
            message += " · 最近閱讀"
        self.query_one("#shelf-status", Static).update(Text(message, no_wrap=True, overflow="ellipsis"))
        self.update_help()

    def on_resize(self):
        if hasattr(self, "entries"):
            self.call_after_refresh(self.refresh_books)

    def on_descendant_focus(self):
        if hasattr(self, "entries"):
            self.update_help()

    @on(DataTable.RowHighlighted, "#books")
    def selection_changed(self):
        if hasattr(self, "entries"):
            self.update_help()

    def update_help(self):
        compact = self.size.width < 80
        panic = self.reader.config.panic_key.upper().replace("CTRL", "Ctrl")
        if self.app.focused is self.query_one("#search", Input):
            first = "Enter 回清單  Esc 清除／上層"
            second = f"←→ 游標  {panic} 離開" if compact else f"僅搜尋此資料夾（不含子資料夾）  ·  ←→ 游標  Backspace 刪字  ·  {panic} 離開"
        else:
            entry = next((entry for entry in self.entries if str(entry.path) == self.selected_key()), None)
            if entry is not None and not entry.is_directory:
                open_hint = "Enter 閱讀" if entry.supported else "PDF 不支援"
                first = f"↑↓ 選擇  {open_hint}"
            else:
                first = "↑↓ 選擇  → 資料夾  Enter 開啟"
            second = f"← 上層  / 搜尋  q/{panic} 離開"
            if not compact:
                first += "  ·  ← / Backspace 上層  ·  / 搜尋"
                second = f"Esc 清除／上層  ·  r 最近閱讀  ·  F5 重新整理  ·  q / {panic} 離開"
        help_text = Text(first + "\n")
        help_text.append(second, style="dim")
        self.query_one("#shelf-help", Static).update(help_text)

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

    def action_open(self, directories_only=False):
        selected = self.selected_key()
        if selected == "__parent__":
            self.action_parent()
            return
        entry = next((entry for entry in self.entries if str(entry.path) == selected), None)
        if entry is None:
            return
        if entry.is_directory:
            self.navigate(entry.path)
        elif directories_only:
            return
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
    BINDINGS = [Binding("ctrl+s", "save", "儲存", priority=True),
                Binding("escape", "cancel", "取消")]

    def compose(self) -> ComposeResult:
        config = self.app.config
        yield Static("設定 · Tab 切換欄位", classes="heading")
        with VerticalScroll(id="settings-fields"):
            yield Label("書庫資料夾")
            yield Input(config.library, id="library")
            yield Label("空白鍵動作")
            yield Select([("翻一頁", "page"), ("捲動一行", "scroll")], value=config.mode, allow_blank=False, id="mode")
            yield Label("閱讀寬度（20–240 終端格）")
            yield Input(str(config.reading_width), id="width", type="integer")
            yield Label("佈景主題")
            yield Select([(t, t) for t in ("textual-dark", "textual-light", "nord", "gruvbox")],
                         value=config.theme, allow_blank=False, id="theme")
            yield Label("全域離開鍵（ctrl+字母；h、i、j、m 除外）")
            yield Input(config.panic_key, id="panic-key")
            yield Static(Text(f"設定檔：{self.app.config_file}"))
        yield Static("", id="settings-error")
        with Horizontal(classes="buttons", id="settings-actions"):
            yield Button("儲存", id="save", variant="primary")
            yield Button("取消", id="cancel")
        yield Static("Ctrl+S 儲存  Esc 取消\nTab 切欄位", id="settings-help")

    def on_mount(self):
        self.query_one("#library", Input).focus()
        panic = self.app.config.panic_key.upper().replace("CTRL", "Ctrl")
        if self.app.config.panic_key == "ctrl+s":
            hints = "Tab 選儲存後 Enter  Esc 取消\nCtrl+S 急退（不儲存）"
        else:
            hints = f"Ctrl+S 儲存  Esc 取消\nTab 切欄位  {panic} 急退"
        self.query_one("#settings-help", Static).update(Text(
            hints))

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "save" and self.app.config.panic_key == "ctrl+s":
            return False  # The app's priority panic binding always wins; the button still saves.
        return super().check_action(action, parameters)

    @on(Button.Pressed, "#save")
    def action_save(self):
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
            error = self.query_one("#settings-error", Static)
            error.display = True
            error.update(Text(str(exc)))
            return
        self.app.apply_config(config)
        self.app.pop_screen()

    @on(Button.Pressed, "#cancel")
    def action_cancel(self):
        self.app.pop_screen()


class Loading(Screen):
    BINDINGS = [("escape", "cancel", "取消開啟")]

    def compose(self):
        yield Static("開啟 EPUB…", classes="heading")
        yield Static(f"計算全書閱讀進度中，{self.app.config.panic_key.upper().replace('CTRL', 'Ctrl')} 隨時離開。", id="load-status")
        yield Footer()

    def action_cancel(self):
        self.app.cancel_job("load")
        self.app.pop_screen()


class Contents(Screen):
    BINDINGS = [("escape", "cancel", "返回")]

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
        ("space", "space", "空白鍵"),
        ("pagedown,right", "move(1, True)", "下一頁"),
        ("pageup,left", "move(-1, True)", "上一頁"),
        ("down,j", "move(1, False)", "下一行"), ("up,k", "move(-1, False)", "上一行"),
        ("n", "chapter(1)", "下一章"), ("p", "chapter(-1)", "上一章"),
        ("t", "toc", "目錄"), ("f2,s", "settings", "設定"),
        ("home", "start", "章節開頭"), ("end", "end", "章節結尾"),
        ("escape,backspace,b", "back", "書櫃"),
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
        yield Static("", id="reading-help")

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
        cells = min(20, max(4, self.size.width // 6))
        filled = round(progress * cells)
        self.query_one("#progress", Static).update(Text(
            f"{'━' * filled}{'─' * (cells - filled)} {progress:.1%} · 第 {self.chapter + 1}/{len(self.book.chapters)} 章",
            no_wrap=True, overflow="ellipsis"))
        space_action = "翻一頁" if self.app.config.mode == "page" else "捲動一行"
        panic = self.app.config.panic_key.upper().replace("CTRL", "Ctrl")
        self.set_class(self.size.width < 70, "narrow")
        if self.size.width < 70:
            help_text = (f"Esc/⌫ 書櫃  F2 設定  t 目錄\n"
                         f"←→ 翻頁  ↑↓ 一行  空白 {space_action}\n"
                         f"q 離開  {panic} 急退")
        else:
            help_text = (f"Esc/⌫ 書櫃  F2 設定  t 目錄  q / {panic} 離開\n"
                         f"←→ 翻頁  ↑↓ 一行  空白 {space_action}  ·  n/p 切章  Home/End 首尾")
        self.query_one("#reading-help", Static).update(Text(help_text))

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

    def action_space(self):
        self.action_move(1, self.app.config.mode == "page")

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
                Binding("ctrl+c", "panic", "離開", show=False, priority=True),
                Binding("q", "quit_from_q", "離開", priority=False)]
    CSS = """
    Screen { layout: vertical; }
    .heading { height: 2; text-style: bold; padding: 0 1; }
    Shelf { padding: 0 2; }
    Shelf.narrow { padding: 0 1; }
    #shelf-header { height: 1; }
    #shelf-title { width: 1fr; padding: 0 1; }
    #shelf-settings { width: 10; min-width: 10; height: 1; border: none; padding: 0; background: transparent; color: $text-muted; }
    #shelf-settings:focus { color: $text; background: $primary 20%; text-style: bold; }
    #shelf-path { height: 1; padding: 0 1; margin-bottom: 1; }
    #shelf-search { height: 1; padding: 0 1; }
    #search-label { width: 2; height: 1; color: $text-muted; }
    #search { width: 1fr; height: 1; border: none; padding: 0; background: transparent; }
    #search:focus { background: $primary 10%; }
    #shelf-status { height: 1; padding: 0 1; color: $text-muted; }
    #shelf-help { height: 2; margin-top: 1; padding: 0 1; }
    Shelf.compact #shelf-path { margin-bottom: 0; }
    Shelf.compact #shelf-help { margin-top: 0; }
    #books { overflow-x: hidden; background: transparent; }
    #books > .datatable--header { background: $surface; color: $text-muted; text-style: none; }
    #books > .datatable--cursor { background: $primary 20%; color: $text; text-style: none; }
    #books, #toc { height: 1fr; }
    #settings-fields { padding: 0 2; height: 1fr; }
    #settings-fields Label { margin-top: 1; }
    #settings-error { color: $error; height: auto; max-height: 3; margin: 0 2; display: none; }
    #settings-actions { margin: 0 2; }
    #settings-help { height: 2; padding: 0 2; }
    .buttons { height: 3; margin-top: 1; }
    .buttons Button { margin-right: 2; }
    #reading-area { height: 1fr; align-horizontal: center; overflow: hidden; }
    #text { height: auto; }
    #progress { height: 1; }
    #reading-help { height: 2; padding: 0 1; }
    Reading.narrow #reading-help { height: 3; }
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
                    f"載入章節 {value[0]}/{value[1]}… · {self.config.panic_key.upper().replace('CTRL', 'Ctrl')} 隨時離開")
        self.background("load", lambda cancel, progress: load_book(entry.path, cancel,
                        lambda count, total: progress((count, total))), finished, report)

    def action_panic(self):
        # Positions are already durable after every move. Never wait for extraction to finish.
        for cancel in self.jobs.values():
            cancel.set()
        self.jobs.clear()
        self.exit()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "quit_from_q":
            # Non-priority binding plus an explicit menu guard: dropdown type-ahead
            # may leave letters unhandled, but must never turn them into an exit.
            if self.focused is not None and any(
                isinstance(widget, (Input, Select)) for widget in self.focused.ancestors_with_self
            ):
                return False
            if any(select.expanded for select in self.screen.query(Select)):
                return False
        return super().check_action(action, parameters)

    def action_quit_from_q(self):
        if self.check_action("quit_from_q", ()):
            self.action_panic()

    def on_unmount(self):
        for cancel in self.jobs.values():
            cancel.set()
