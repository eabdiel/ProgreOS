"""Portable Progre Cockpit launcher.

Run with: python main.py
Creates a private Python environment on first launch, installs the small
Cockpit Python requirements, then starts the Cockpit. Large AI/voice assets
remain explicit Cockpit-managed dependencies.
"""
from __future__ import annotations
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / '.progre-venv'
REQ = ROOT / 'bridge' / 'requirements.txt'


def vpython():
    return VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def main():
    if not vpython().exists():
        print('[Progre] Creating private Cockpit environment...')
        venv.EnvBuilder(with_pip=True).create(VENV)
    py = str(vpython())
    marker = VENV / '.requirements-ready'
    if not marker.exists():
        print('[Progre] Installing Cockpit dependencies...')
        subprocess.check_call([py, '-m', 'pip', 'install', '-r', str(REQ)])
        marker.write_text('ready\n')
    os.execv(py, [py, str(ROOT / 'cockpit' / 'main.py')])


if __name__ == '__main__':
    main()
