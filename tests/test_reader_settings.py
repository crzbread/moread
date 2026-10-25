"""Regressions for the real reader → settings → reader/shelf interaction."""
import pytest
from textual.widgets import Button, Input, Label, Select, Static
from wcwidth import wcswidth

from dbb_reader.app import Reading, Settings, Shelf
from dbb_reader.config import load_config
from test_app import make_app, ready, until


def visible_text(widget):
    return "\n".join(strip.text for strip in widget.render_lines(widget.size.region))


async def open_reading(app, pilot):
    await ready(app, pilot)
    await pilot.press("enter")
    await until(pilot, lambda: isinstance(app.screen, Reading))
    return app.screen


@pytest.mark.parametrize("size", [(40, 18), (80, 24)])
async def test_reader_return_and_settings_help_really_visible(make_epub, tmp_path, size):
    path = make_epub(chapters=[("body.xhtml", "測試章節", "中文閱讀測試。" * 1000)])
    app = make_app(tmp_path)
    async with app.run_test(size=size) as pilot:
        reading = await open_reading(app, pilot)
        help_widget = reading.query_one("#reading-help", Static)
        text = visible_text(help_widget)
        assert help_widget.region in app.screen.region
        for key in ("Esc", "⌫", "書櫃", "F2", "設定", "空白", "Ctrl+D"):
            assert key in text
        assert all(wcswidth(line) <= help_widget.content_size.width
                   for line in help_widget.content.plain.splitlines())
        await pilot.press("right")
        position = (reading.chapter, reading.text_offset)
        await pilot.press("backspace")
        assert isinstance(app.screen, Shelf) and not app._exit
        assert app.screen.selected_key() == str(path)
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, Reading))
        assert (app.screen.chapter, app.screen.text_offset) == position
        await pilot.press("f2")
        await until(pilot, lambda: isinstance(app.screen, Settings))
        await pilot.press("escape", "escape")
        assert isinstance(app.screen, Shelf) and not app._exit


@pytest.mark.parametrize("size", [(40, 18), (80, 24)])
async def test_settings_pinned_actions_errors_save_and_cancel_roundtrip(make_epub, tmp_path, size):
    make_epub(chapters=[("body.xhtml", "測試章節", "中文閱讀測試。" * 1000)])
    app = make_app(tmp_path)
    async with app.run_test(size=size) as pilot:
        reading = await open_reading(app, pilot)
        await pilot.press("right")
        position = (reading.chapter, reading.text_offset)
        await pilot.press("s")
        await until(pilot, lambda: isinstance(app.screen, Settings))
        settings = app.screen
        assert app.focused is settings.query_one("#library", Input)
        for selector in ("#save", "#cancel"):
            button = settings.query_one(selector, Button)
            assert button.region in settings.region and visible_text(button).strip()
        action_regions = [settings.query_one(selector).region for selector in ("#save", "#cancel")]
        settings.query_one("#settings-fields").scroll_end(animate=False)
        await pilot.pause()
        assert action_regions == [settings.query_one(selector).region for selector in ("#save", "#cancel")]
        hints = visible_text(settings.query_one("#settings-help", Static))
        assert "Ctrl+S" in hints and "Esc" in hints and "Ctrl+D" in hints
        assert any("空白鍵動作" in str(label.content) for label in settings.query(Label))
        settings.query_one("#width", Input).value = "0"
        settings.query_one("#width", Input).focus()
        await pilot.press("ctrl+s")
        assert app.screen is settings
        error = settings.query_one("#settings-error", Static)
        assert error.region in settings.region and "20" in visible_text(error)
        assert all(settings.query_one(selector).region in settings.region for selector in ("#save", "#cancel"))
        settings.query_one("#width", Input).value = "26"
        settings.query_one("#mode", Select).focus()
        await pilot.press("enter", "down", "enter")
        assert settings.query_one("#mode", Select).value == "scroll"
        settings.query_one("#theme", Select).value = "nord"
        settings.query_one("#panic-key", Input).value = "ctrl+x"
        await pilot.press("ctrl+s")
        await until(pilot, lambda: app.screen is reading)
        assert load_config(app.config_file)[0] == app.config
        assert app.config.mode == "scroll" and app.theme == "nord"
        assert reading.query_one("#text").size.width == 26
        assert (reading.chapter, reading.text_offset) == position
        assert "空白 捲動一行" in visible_text(reading.query_one("#reading-help", Static))
        assert "Ctrl+X" in visible_text(reading.query_one("#reading-help", Static))
        saved = app.config_file.read_bytes()
        await pilot.press("f2")
        await until(pilot, lambda: isinstance(app.screen, Settings))
        app.screen.query_one("#width", Input).value = "30"
        app.screen.query_one("#mode", Select).value = "page"
        app.screen.query_one("#theme", Select).value = "gruvbox"
        await pilot.press("escape")
        assert app.screen is reading and app.config.reading_width == 26
        assert app.config.mode == "scroll" and app.theme == "nord"
        assert app.config_file.read_bytes() == saved
        assert (reading.chapter, reading.text_offset) == position
        await pilot.press("ctrl+x")
        await pilot.pause()
        assert app._exit


@pytest.mark.parametrize("mode", ["page", "scroll"])
async def test_space_mode_observable_arrows_unchanged(make_epub, tmp_path, mode):
    make_epub(chapters=[("body.xhtml", "測試章節", "中文閱讀測試。" * 1000)])
    app = make_app(tmp_path, mode=mode, reading_width=30)
    async with app.run_test(size=(80, 24)) as pilot:
        reading = await open_reading(app, pilot)
        reading.goto(0, 0)
        await pilot.press("down")
        one_line = reading.text_offset
        reading.goto(0, 0)
        await pilot.press("right")
        one_page = reading.text_offset
        assert 0 < one_line < one_page
        reading.goto(0, 0)
        await pilot.press("space")
        assert reading.text_offset == (one_page if mode == "page" else one_line)
        await pilot.press("left")
        assert reading.text_offset == 0
        await pilot.press("q")
        await pilot.pause()
        assert app._exit  # q remains application exit, not return-to-shelf.


async def test_ctrl_s_panic_collision_keeps_button_save_and_honest_hints(make_epub, tmp_path):
    make_epub()
    app = make_app(tmp_path, panic_key="ctrl+s")
    async with app.run_test(size=(40, 18)) as pilot:
        await ready(app, pilot)
        await pilot.press("f2")
        await until(pilot, lambda: isinstance(app.screen, Settings))
        settings = app.screen
        hints = visible_text(settings.query_one("#settings-help", Static))
        assert "Ctrl+S 儲存" not in hints
        assert "Tab" in hints and "Enter" in hints and "Ctrl+S 急退" in hints
        assert settings.check_action("save", ()) is False
        settings.query_one("#width", Input).value = "26"
        settings.query_one("#save", Button).focus()
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, Shelf))
        assert load_config(app.config_file)[0].reading_width == 26
        assert app.config.panic_key == "ctrl+s"
        await pilot.press("f2")
        await until(pilot, lambda: isinstance(app.screen, Settings))
        app.screen.query_one("#width", Input).value = "30"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app._exit
        assert load_config(app.config_file)[0].reading_width == 26
