"""Real PTY contract: alternate screen, no mouse capture, clean shell restoration."""
import os
import select
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX PTY verification")


def test_panic_restores_terminal_and_keeps_titles_in_alternate_screen(make_epub, tmp_path):
    import fcntl
    import pty
    import struct
    import termios

    make_epub()
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    child = subprocess.Popen(
        [sys.executable, "-m", "dbb_reader", "--library", str(tmp_path),
         "--config", str(tmp_path / "settings.toml"), "--state", str(tmp_path / "positions.json")],
        stdin=slave, stdout=slave, stderr=slave,
        env={**os.environ, "TERM": "xterm-256color"},
    )
    output = bytearray()
    def read_until(predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            if select.select([master], [], [], .05)[0]:
                output.extend(os.read(master, 65536))
        assert predicate(), "Terminal did not reach the expected state"
    try:
        read_until(lambda: "真正書名".encode() in output)
        os.write(master, b"/")
        read_until(lambda: "←→ 游標".encode() in output)
        os.write(master, b"\x04")
        read_until(lambda: b"\x1b[?1049l" in output)
        assert child.wait(timeout=3) == 0
        assert termios.tcgetattr(slave) == before
        assert b"\x1b[?1049h" in output
        for mode in (1000, 1002, 1003, 1006):
            assert f"\x1b[?{mode}h".encode() not in output
        # Book metadata is drawn only inside the alternate screen, never into OSC titles
        # or normal-screen output after cleanup.
        import re
        title = "真正書名".encode()
        assert title not in output.split(b"\x1b[?1049l", 1)[1]
        assert all(title not in match for match in re.findall(rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", output))
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)
        os.close(slave)
