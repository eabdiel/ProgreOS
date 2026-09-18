# Progre Voice Bridge

Local listener and control-plane service between Progre hardware and
higher-level ProgreTech runtimes.

## Development

Create the environment:

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt

Launch the Bridge:

    .venv/bin/python main.py

Initial protocol:

- GET /health
- POST /api/v1/device/hello

The Flask application is intentionally launched from main.py so the
same service can evolve into the Progre Cockpit.
