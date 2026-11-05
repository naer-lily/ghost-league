"""Raw TCP printing to a network thermal printer (usually port 9100)."""

from __future__ import annotations

import socket

ESC = b"\x1b"
GS = b"\x1d"
CUT = GS + b"V\x00"  # GS V 0: full cut


class PrinterError(Exception):
    """The printer could not be reached or the payload could not be sent."""


def test_page() -> bytes:
    """A small ASCII-only ESC/POS test page ending in a full cut."""
    text = (
        b"Ghost League print test\n"
        b"------------------------\n"
        b"If you can read this,\n"
        b"the printer connection works.\n"
    )
    # ESC @ (initialize), ESC a 1 (center), text, feed, GS V 0 (cut).
    return ESC + b"@" + ESC + b"a\x01" + text + b"\n\n\n" + CUT


class PrinterClient:
    def __init__(self, host: str, port: int, timeout: float = 10.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def probe(self) -> None:
        """Open and immediately close a TCP connection to verify reachability."""
        sock: socket.socket | None = None
        try:
            sock = socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            )
        except (OSError, ValueError) as exc:
            raise PrinterError(
                f"printer {self.host}:{self.port} is unreachable: {exc}"
            ) from exc
        finally:
            if sock is not None:
                sock.close()

    def send(self, payload: bytes) -> None:
        if not isinstance(payload, (bytes, bytearray)):
            raise PrinterError("printer payload must be bytes")
        data = bytes(payload)
        sock: socket.socket | None = None
        try:
            sock = socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            )
            sock.settimeout(self.timeout)
            sock.sendall(data)
            try:
                sock.shutdown(socket.SHUT_WR)
            except OSError:
                # The bytes are already flushed; a failed half-close is not fatal.
                pass
        except (OSError, ValueError) as exc:
            raise PrinterError(
                f"printer {self.host}:{self.port} send failed: {exc}"
            ) from exc
        finally:
            if sock is not None:
                sock.close()
