from __future__ import annotations

import atexit
import json
import threading
import time

_sessions = {}
_sessions_lock = threading.Lock()


class _Session:
    def __init__(self, serial_port):
        self.serial_port = serial_port
        self.ser = None
        self.lock = threading.RLock()

    def _open(self, recovery=False):
        import serial

        if self.ser is not None and self.ser.is_open:
            return self.ser

        ser = serial.Serial(
            port=None,
            baudrate=115200,
            timeout=0.25,
            write_timeout=2,
            dsrdtr=False,
            rtscts=False,
        )
        ser.dtr = False
        ser.rts = False
        ser.port = self.serial_port
        ser.open()
        self.ser = ser

        # Opening ESP32-S3 native USB may reset the board. A recovery reopen
        # therefore needs a longer boot allowance than the initial session open.
        time.sleep(3.0 if recovery else 1.35)
        ser.reset_input_buffer()
        return ser

    def close(self):
        with self.lock:
            if self.ser is not None:
                try:
                    if self.ser.is_open:
                        self.ser.close()
                finally:
                    self.ser = None

    def command(self, cmd, timeout=8.0, recovery=False, **payload):
        request = {"cmd": cmd, **payload}
        wire = ("PROGRE " + json.dumps(request, separators=(",", ":")) + "\n").encode()

        with self.lock:
            ser = self._open(recovery=recovery)
            ser.reset_input_buffer()
            ser.write(wire)
            ser.flush()

            deadline = time.monotonic() + timeout
            reply_prefix = "PROGRE_REPLY "
            buffered = ""

            while time.monotonic() < deadline:
                raw = ser.readline()
                if not raw:
                    continue

                text = raw.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue

                # ESP-IDF logs can occasionally interleave with stdout. Search
                # for the protocol marker instead of requiring column zero.
                marker = text.find(reply_prefix)
                if marker < 0:
                    continue

                candidate = text[marker + len(reply_prefix):]
                buffered += candidate
                try:
                    reply = json.loads(buffered)
                except json.JSONDecodeError:
                    continue

                if reply.get("cmd") == cmd:
                    return reply

            raise TimeoutError(
                f"Progre did not answer {cmd!r} on {self.serial_port}"
            )


def _session(serial_port):
    with _sessions_lock:
        session = _sessions.get(serial_port)
        if session is None:
            session = _Session(serial_port)
            _sessions[serial_port] = session
        return session


def command(serial_port, cmd, timeout=8.0, **payload):
    session = _session(serial_port)

    try:
        return session.command(cmd, timeout=timeout, **payload)

    except TimeoutError:
        # Native ESP32-S3 USB can leave an apparently-open serial handle
        # alive while the protocol endpoint is no longer responsive.
        # Recover once by reopening the transport and retrying the command.
        session.close()

        try:
            return session.command(
                cmd,
                timeout=max(timeout, 8.0),
                recovery=True,
                **payload,
            )
        except Exception:
            session.close()
            raise

    except Exception:
        ser = session.ser

        if ser is None or not getattr(ser, "is_open", False):
            with _sessions_lock:
                if _sessions.get(serial_port) is session:
                    _sessions.pop(serial_port, None)

        raise


def close(serial_port=None):
    with _sessions_lock:
        if serial_port is None:
            items = list(_sessions.items())
            _sessions.clear()
        else:
            session = _sessions.pop(serial_port, None)
            items = [(serial_port, session)] if session else []

    for _, session in items:
        if session is not None:
            session.close()


atexit.register(close)
