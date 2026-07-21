"""Bidirectional QEMU serial-console + QMP helpers for the isolated VM driver.

Uses a plain TCP loopback socket for the serial chardev (portable, no platform
AF_UNIX quirks). Screen state is tracked with a real VT100 terminal emulator
(`pyte`) rather than naive ANSI stripping -- Textual redraws the screen with
cursor-positioned partial updates, and a byte-order text search over stripped
escape sequences reorders/garbles content. `pyte` gives a coherent, position-
aware 80x24 snapshot to search against, matching what a human would actually
see on the console.
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass, field

import pyte


TERMINAL_COLUMNS = 80
TERMINAL_ROWS = 24


@dataclass
class SerialConsole:
    host: str
    port: int
    columns: int = TERMINAL_COLUMNS
    rows: int = TERMINAL_ROWS
    sock: socket.socket | None = field(default=None, init=False)
    _raw_log: bytearray = field(default_factory=bytearray, init=False)
    _screen: pyte.Screen = field(init=False)
    _stream: pyte.Stream = field(init=False)

    def __post_init__(self) -> None:
        self._screen = pyte.Screen(self.columns, self.rows)
        self._stream = pyte.Stream(self._screen)

    def connect(self, *, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        last_exc: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=2.0)
                self.sock.settimeout(0.5)
                return
            except OSError as exc:  # port not listening yet
                last_exc = exc
                time.sleep(0.5)
        raise TimeoutError(f"Could not connect to serial console {self.host}:{self.port}") from last_exc

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _drain(self, duration: float) -> None:
        assert self.sock is not None
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            try:
                chunk = self.sock.recv(65536)
                if chunk:
                    self._raw_log.extend(chunk)
                    self._stream.feed(chunk.decode("utf-8", errors="replace"))
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break

    def send(self, text: str) -> None:
        assert self.sock is not None
        self.sock.sendall(text.encode("utf-8"))

    def send_line(self, text: str = "") -> None:
        self.send(text + "\r")

    def send_key(self, key: str) -> None:
        mapping = {
            "tab": "\t",
            "enter": "\r",
            "escape": "\x1b",
            "up": "\x1b[A",
            "down": "\x1b[B",
        }
        self.send(mapping.get(key, key))

    def screen_text(self, *, tail_bytes: int | None = None) -> str:
        """Return the current emulated 80x24 screen as text, top to bottom.

        Always drains any bytes sitting in the socket's receive buffer first --
        nothing else pulls data off the wire on its own, so a bare read right
        after a `send()` would otherwise see stale, pre-response state.
        """
        self._drain(0.3)
        return "\n".join(self._screen.display)

    def scrollback_text(self, *, tail_bytes: int = 20000) -> str:
        """Raw decoded bytes (includes scrolled-off shell output pyte discards)."""
        self._drain(0.3)
        return bytes(self._raw_log[-tail_bytes:]).decode("utf-8", errors="replace")

    def wait_for(self, *needles: str, timeout: float = 60.0, poll: float = 1.0) -> str:
        """Poll until any needle appears on the emulated screen OR raw scrollback."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._drain(poll)
            screen = self.screen_text()
            for needle in needles:
                if needle in screen:
                    return needle
            raw_tail = self.scrollback_text(tail_bytes=4000)
            for needle in needles:
                if needle in raw_tail:
                    return needle
        raise TimeoutError(f"Timed out waiting for any of {needles!r} on serial console")

    def save_log(self, path: str) -> None:
        with open(path, "wb") as handle:
            handle.write(bytes(self._raw_log))


@dataclass
class QmpClient:
    host: str
    port: int
    sock: socket.socket | None = field(default=None, init=False)
    _buffer: bytes = field(default=b"", init=False)

    def connect(self, *, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        last_exc: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=5.0)
                break
            except OSError as exc:
                last_exc = exc
                time.sleep(0.5)
        else:
            raise TimeoutError(f"Could not connect to QMP {self.host}:{self.port}") from last_exc
        self._read_json()  # greeting
        self._send({"execute": "qmp_capabilities"})
        self._read_json()

    def _send(self, payload: dict) -> None:
        assert self.sock is not None
        self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))

    def _read_json(self, *, timeout: float = 15.0) -> dict:
        assert self.sock is not None
        self.sock.settimeout(timeout)
        while b"\n" not in self._buffer:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("QMP connection closed")
            self._buffer += chunk
        line, _, rest = self._buffer.partition(b"\n")
        self._buffer = rest
        return json.loads(line.decode("utf-8"))

    def command(self, execute: str, **arguments) -> dict:
        payload: dict = {"execute": execute}
        if arguments:
            payload["arguments"] = arguments
        self._send(payload)
        while True:
            response = self._read_json()
            if "event" in response:
                continue
            return response

    def system_powerdown(self) -> None:
        self.command("system_powerdown")

    def quit(self) -> None:
        try:
            self.command("quit")
        except (ConnectionError, OSError):
            pass

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None
