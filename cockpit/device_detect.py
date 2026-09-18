from __future__ import annotations
import glob
import platform
import time
from pathlib import Path

ESPRESSIF_VID = 0x303A


def _linux_candidates():
    result = []
    for name in sorted(glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')):
        tty = Path(name).name
        base = Path('/sys/class/tty') / tty / 'device'
        try:
            cursor = base.resolve()
        except Exception:
            cursor = base
        vid = pid = None
        for _ in range(6):
            try:
                vp, pp = cursor / 'idVendor', cursor / 'idProduct'
                if vp.exists():
                    vid = int(vp.read_text().strip(), 16)
                    pid = int(pp.read_text().strip(), 16) if pp.exists() else None
                    break
            except Exception:
                pass
            if cursor.parent == cursor:
                break
            cursor = cursor.parent
        result.append({'port': name, 'vid': vid, 'pid': pid})
    return result


def _pyserial_candidates():
    try:
        from serial.tools import list_ports
    except Exception:
        return []
    return [
        {'port': p.device, 'vid': p.vid, 'pid': p.pid,
         'description': p.description, 'manufacturer': p.manufacturer}
        for p in list_ports.comports()
    ]


def candidates():
    rows = _pyserial_candidates()
    if not rows and platform.system() == 'Linux':
        rows = _linux_candidates()
    seen, out = set(), []
    for row in rows:
        port = row.get('port')
        if not port or port in seen:
            continue
        seen.add(port)
        row['espressif'] = row.get('vid') == ESPRESSIF_VID
        out.append(row)
    return out


def _probe_console(port):
    try:
        import serial
    except Exception:
        return None, 'pyserial unavailable'
    try:
        with serial.Serial(port, 115200, timeout=0.15) as ser:
            ser.reset_input_buffer()
            deadline = time.monotonic() + 1.2
            chunks = []
            while time.monotonic() < deadline:
                data = ser.read(1024)
                if data:
                    chunks.append(data)
            text = b''.join(chunks).decode('utf-8', errors='ignore')
            return text, None
    except Exception as exc:
        return None, str(exc)


def detect():
    rows = candidates()
    esp = [r for r in rows if r.get('espressif')]
    if not esp:
        return {'state': 'not_detected', 'port': None, 'hardware': None,
                'firmware': None, 'firmware_version': None,
                'message': 'No Espressif USB device detected.', 'candidates': rows}

    dev = esp[0]
    try:
        from device_control import command
        status = command(dev['port'], 'status', timeout=2.5)
        if status.get('ok') and status.get('device') == 'progre':
            return {'state': 'progre_detected', 'port': dev['port'],
                    'hardware': 'AIPI Lite / ESP32-S3 compatible',
                    'firmware': 'Progre OS', 'firmware_version': status.get('version'),
                    'message': 'Progre OS detected. Device is ready for commissioning.',
                    'status': status, 'candidates': rows}
    except Exception:
        pass
    text, error = _probe_console(dev['port'])
    firmware = 'unknown'
    state = 'compatible_detected'
    message = 'Compatible AIPI Lite / ESP32-S3 hardware detected.'

    if text and ('PROGRE' in text.upper() or 'PROGRE_OS' in text.upper()):
        firmware = 'Progre OS'
        state = 'progre_detected'
        message = 'Progre OS detected. Device is ready for commissioning.'
    elif error:
        state = 'port_busy_or_recovery'
        message = 'Compatible hardware detected, but the serial port is busy or the device may be in recovery mode.'
    else:
        firmware = 'stock_or_unknown'
        state = 'stock_or_unknown'
        message = 'Compatible hardware detected without a Progre signature. Treat as stock/unknown until a verified backup is created.'

    return {'state': state, 'port': dev['port'],
            'hardware': 'AIPI Lite / ESP32-S3 compatible',
            'firmware': firmware, 'firmware_version': None,
            'message': message, 'probe_error': error, 'candidates': rows}
