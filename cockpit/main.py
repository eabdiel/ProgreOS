from pathlib import Path
import time
import sys
import json

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_DIR = ROOT / "bridge"

if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

from progre_runtime import discover as runtime_discover
from progre_runtime import readiness as runtime_readiness
from device_detect import detect as detect_aipi

LIFECYCLE_FILE = ROOT / "data/device/lifecycle.json"
DEPENDENCIES_FILE = ROOT / "runtime/dependencies.json"

import json
import sys
import urllib.request
import socket

from device_control import command as device_command
from runtime_installer import start as installer_start
from runtime_installer import status as installer_status
from device_recovery import backup as recovery_backup
from device_recovery import verified_backup
from device_recovery import install_preflight
from device_recovery import restore_preflight
from device_recovery import install_progre
from device_recovery import restore_backup

from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bridge"
sys.path.insert(0, str(BRIDGE))

from progre_config import DEFAULT_CONFIG, load_config, save_config

app = Flask(__name__)

OLLAMA = "http://127.0.0.1:11434/api/tags"
HEALTH = "http://127.0.0.1:8765/health"

VOICE_DIR = ROOT / "runtime" / "voices"


def load_lifecycle():
    try:
        return json.loads(LIFECYCLE_FILE.read_text())
    except Exception:
        return {
            "schema": 1,
            "device": None,
            "detection": {
                "state": "not_scanned",
                "port": None,
                "hardware": None,
                "firmware": None,
                "firmware_version": None,
            },
            "recovery": {
                "stock_backup": None,
                "backup_verified": False,
            },
            "provisioning": {
                "progre_installed": False,
                "last_provisioned": None,
            },
        }


def dependency_status():
    ready = runtime_readiness()
    discovered = runtime_discover()

    try:
        definitions = json.loads(DEPENDENCIES_FILE.read_text())
    except Exception:
        definitions = {}

    result = {}

    for name, definition in definitions.items():
        result[name] = {
            "label": definition.get("label", name),
            "required": definition.get("required", True),
            "installable": definition.get("installable", True),
            "ready": bool(ready.get(name, False)),
            "detected": discovered.get(name),
        }

    # AI model is intentionally separate from the Ollama runtime.
    # Existing /api/status already discovers installed Ollama models.
    installed_models = models()
    cfg_model = load_config().get("model")
    result["ai_model"] = {
        "label": "Local AI Model",
        "required": True,
        "installable": True,
        "ready": cfg_model in installed_models,
        "detected": cfg_model if cfg_model in installed_models else None,
    }

    return result


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=2) as r:
        return json.loads(r.read())


def models():
    try:
        return [
            x["name"]
            for x in fetch_json(OLLAMA).get("models", [])
            if x.get("name")
        ]
    except Exception:
        return []


def voices():
    if not VOICE_DIR.exists():
        return []

    return sorted(x.name for x in VOICE_DIR.glob("*.onnx"))


def bridge():
    try:
        return {
            "online": True,
            "data": fetch_json(HEALTH),
        }
    except Exception as exc:
        return {
            "online": False,
            "error": str(exc),
        }


@app.get("/api/status")
def status():
    return jsonify(
        config=load_config(),
        models=models(),
        voices=voices(),
        bridge=bridge(),
    )


@app.post("/api/config")
def config():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="JSON object required"), 400

    try:
        cfg = save_config(data)
    except Exception as exc:
        return jsonify(error=str(exc)), 400

    return jsonify(status="saved", config=cfg)


@app.post("/api/reset")
def reset():
    return jsonify(
        status="reset",
        config=save_config(DEFAULT_CONFIG),
    )


@app.get("/api/runtime")
def api_runtime():
    return {
        "ok": True,
        "dependencies": dependency_status(),
    }


@app.get("/api/device")
def api_device():
    return {
        "ok": True,
        "device": load_lifecycle(),
    }


@app.post("/api/device/detect")
def api_device_detect():
    lifecycle = load_lifecycle()
    detection = detect_aipi()
    lifecycle["detection"] = detection
    LIFECYCLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LIFECYCLE_FILE.write_text(json.dumps(lifecycle, indent=2) + "\n")
    return {"ok": True, "implemented": True, "device": lifecycle}


@app.get("/api/device/recovery")
def api_device_recovery_status():
    return {
        "ok": True,
        "recovery": verified_backup(),
    }


@app.post("/api/device/recovery/install")
def api_device_recovery_install():
    payload = request.get_json(silent=True) or {}

    if payload.get("confirmation") != "INSTALL PROGRE OS":
        return {
            "ok": False,
            "error": "confirmation_required",
            "message": "Type INSTALL PROGRE OS exactly to continue.",
        }, 409

    port = current_device_port()

    if not port:
        return {
            "ok": False,
            "error": "device_not_detected",
            "message": "Detect the attached AIPI Lite first.",
        }, 409

    try:
        # Backend preflight is authoritative and is repeated immediately
        # before install_progre performs its own fresh recovery gate.
        install_preflight()
        return install_progre(port)

    except Exception as exc:
        return {
            "ok": False,
            "error": "install_failed",
            "message": str(exc),
        }, 500


@app.post("/api/device/recovery/restore")
def api_device_recovery_restore():
    payload = request.get_json(silent=True) or {}

    if payload.get("confirmation") != "RESTORE VERIFIED BACKUP":
        return {
            "ok": False,
            "error": "confirmation_required",
            "message": "Type RESTORE VERIFIED BACKUP exactly to continue.",
        }, 409

    port = current_device_port()

    if not port:
        return {
            "ok": False,
            "error": "device_not_detected",
            "message": "Detect the attached AIPI Lite first.",
        }, 409

    try:
        restore_preflight()
        return restore_backup(port)

    except Exception as exc:
        return {
            "ok": False,
            "error": "restore_failed",
            "message": str(exc),
        }, 500


@app.get("/api/device/recovery/preflight")
def api_device_recovery_preflight():
    result = {
        "ok": True,
        "install": {
            "ready": False,
        },
        "restore": {
            "ready": False,
        },
    }

    try:
        result["install"] = install_preflight()
    except Exception as exc:
        result["install"] = {
            "ready": False,
            "message": str(exc),
        }

    try:
        result["restore"] = restore_preflight()
    except Exception as exc:
        result["restore"] = {
            "ready": False,
            "message": str(exc),
        }

    return result


@app.post("/api/device/recovery/backup")
def api_device_recovery_backup():
    port = current_device_port()

    if not port:
        return {
            "ok": False,
            "error": "device_not_detected",
            "message": "Detect the attached AIPI Lite first.",
        }, 409

    detection = load_lifecycle().get("detection", {})
    state = detection.get("state")

    if state not in {
        "stock_or_unknown",
        "compatible_detected",
        "port_busy_or_recovery",
        "progre_detected",
    }:
        return {
            "ok": False,
            "error": "backup_not_available",
            "message": "The attached hardware is not in a backup-capable state.",
        }, 409

    try:
        result = recovery_backup(
            port,
            source_state=device.get("state", "unknown"),
        )
        return result
    except Exception as exc:
        return {
            "ok": False,
            "error": "backup_failed",
            "message": str(exc),
        }, 500


@app.post("/api/install/<component>")
def api_install_component(component):
    allowed = set(dependency_status())

    if component not in allowed:
        return {
            "ok": False,
            "error": "unknown_component",
        }, 404

    current = dependency_status().get(component, {})

    if current.get("ready"):
        return {
            "ok": True,
            "component": component,
            "state": "ready",
            "message": "Dependency is already ready.",
        }

    result = installer_start(component)

    if not result.get("ok"):
        code = 409 if result.get("error") == "already_installing" else 500
        return result, code

    return result, 202


@app.get("/api/install/status")
def api_install_status_all():
    return {
        "ok": True,
        "jobs": installer_status(),
        "dependencies": dependency_status(),
    }


@app.get("/api/install/status/<component>")
def api_install_status_component(component):
    if component not in dependency_status():
        return {"ok": False, "error": "unknown_component"}, 404

    return {
        "ok": True,
        "job": installer_status(component),
        "dependency": dependency_status().get(component),
    }



def current_device_port():
    return load_lifecycle().get("detection", {}).get("port")

def local_lan_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()

@app.get("/api/device/status-live")
def api_device_status_live():
    port=current_device_port()
    if not port: return {"ok":False,"error":"device_not_detected"},409
    try: return device_command(port,"status")
    except Exception as exc: return {"ok":False,"error":"device_unavailable","message":str(exc)},503

@app.post("/api/device/wifi/scan")
def api_wifi_scan():
    port=current_device_port()
    if not port: return {"ok":False,"error":"device_not_detected"},409
    try: return device_command(port,"wifi_scan",timeout=15)
    except Exception as exc: return {"ok":False,"error":"scan_failed","message":str(exc)},503

@app.post("/api/device/configure")
def api_device_configure():
    port=current_device_port(); data=request.get_json(silent=True) or {}
    if not port: return {"ok":False,"error":"device_not_detected"},409
    ssid = str(data.get("ssid", "")).strip()
    password = str(data.get("password", ""))
    host = str(data.get("bridge_host") or local_lan_ip()).strip()

    try:
        bridge_port = int(data.get("bridge_port") or 8765)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_bridge_port"}, 400

    if not ssid:
        return {"ok": False, "error": "ssid_required"}, 400

    if not host:
        return {"ok": False, "error": "bridge_host_required"}, 400

    if not 1 <= bridge_port <= 65535:
        return {"ok": False, "error": "invalid_bridge_port"}, 400

    try:
        bridge_reply = device_command(
            port,
            "bridge_set",
            host=host,
            port=bridge_port,
        )

        if not bridge_reply.get("ok"):
            return {
                "ok": False,
                "error": "bridge_set_failed",
                "bridge": bridge_reply,
            }, 502

        wifi_reply = device_command(
            port,
            "wifi_set",
            timeout=15,
            ssid=ssid,
            password=password,
        )

        if not wifi_reply.get("ok"):
            return {
                "ok": False,
                "error": "wifi_set_failed",
                "wifi": wifi_reply,
            }, 502

        # wifi_set acknowledgement means credentials were stored.  It does
        # not prove association. Ask Progre to reconnect and then poll the
        # device's authoritative status until the requested network is live.
        reconnect_reply = device_command(
            port,
            "wifi_reconnect",
            timeout=8,
        )

        final_status = None

        # Wi-Fi association can legitimately take several seconds,
        # especially after USB recovery or AP renegotiation. Keep polling
        # authoritative device status for a bounded ~36 second window.
        for _ in range(12):
            time.sleep(2.0)

            try:
                status_reply = device_command(
                    port,
                    "status",
                    timeout=6,
                )
            except Exception:
                continue

            final_status = status_reply

            if (
                status_reply.get("ok")
                and status_reply.get("ssid") == ssid
                and status_reply.get("wifi_state") == "CONNECTED"
            ):
                break

        connected = bool(
            final_status
            and final_status.get("ok")
            and final_status.get("ssid") == ssid
            and final_status.get("wifi_state") == "CONNECTED"
        )

        bridge_health = bridge()

        result = {
            "ok": connected,
            "credentials_stored": True,
            "connected": connected,
            "ssid": ssid,
            "bridge_host": host,
            "bridge_port": bridge_port,
            "bridge_config": bridge_reply,
            "wifi": wifi_reply,
            "reconnect": reconnect_reply,
            "device_status": final_status,
            "bridge_online": bool(bridge_health.get("online")),
        }

        if connected:
            result["message"] = (
                f"Progre connected to {ssid} and is configured for "
                f"{host}:{bridge_port}."
            )
            return result

        result["error"] = "wifi_not_connected"
        result["message"] = (
            "Credentials were stored, but Progre did not reach CONNECTED "
            "state before the commissioning timeout."
        )
        return result, 504

    except Exception as exc:
        return {
            "ok": False,
            "error": "configure_failed",
            "message": str(exc),
        }, 503

@app.post("/api/device/reconnect")
def api_device_reconnect():
    port=current_device_port()
    if not port: return {"ok":False,"error":"device_not_detected"},409
    try: return device_command(port,"wifi_reconnect")
    except Exception as exc: return {"ok":False,"error":"reconnect_failed","message":str(exc)},503

@app.post("/api/device/reboot")
def api_device_reboot():
    port=current_device_port()
    if not port: return {"ok":False,"error":"device_not_detected"},409
    try: return device_command(port,"reboot")
    except Exception as exc: return {"ok":False,"error":"reboot_failed","message":str(exc)},503

@app.get("/api/host/network")
def api_host_network():
    return {"ok":True,"bridge_host":local_lan_ip(),"bridge_port":8765}

@app.get("/")
def index():
    return PAGE


PAGE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Progre Cockpit</title>

<style>
*{box-sizing:border-box}
body{
 margin:0;background:#080808;color:#eee;
 font-family:system-ui,sans-serif
}
header{
 padding:20px 28px;background:#111;
 border-bottom:1px solid #333;
 display:flex;justify-content:space-between;align-items:center
}
.brand{display:flex;align-items:center;gap:15px}
.face{
 width:48px;height:48px;border:1px solid #555;
 border-radius:11px;position:relative;background:#050505
}
.eye{
 position:absolute;top:14px;width:7px;height:11px;
 background:#fff;border-radius:50%
}
.l{left:12px}.r{right:12px}
.mouth{
 position:absolute;bottom:10px;left:16px;
 width:14px;height:2px;background:#fff
}
h1{font-size:20px;margin:0;letter-spacing:.06em}
.sub{font-size:12px;color:#888;margin-top:3px}
.badge{
 border:1px solid #444;border-radius:20px;
 padding:7px 11px;font-size:12px
}
main{max-width:1050px;margin:auto;padding:25px}
.grid{
 display:grid;
 grid-template-columns:repeat(auto-fit,minmax(290px,1fr));
 gap:16px
}
.card{
 background:#111;border:1px solid #292929;
 border-radius:13px;padding:19px
}
h2{
 margin:0 0 15px;font-size:13px;
 letter-spacing:.08em;color:#ccc;text-transform:uppercase
}
label{
 display:block;color:#999;font-size:12px;
 margin:15px 0 6px
}
select,input{
 width:100%;background:#080808;color:#eee;
 border:1px solid #3b3b3b;border-radius:7px;padding:9px
}
input[type=range]{padding:0}
.value{
 text-align:right;color:#aaa;font-size:11px;margin-top:4px
}
.row{
 display:flex;justify-content:space-between;
 border-top:1px solid #292929;padding:10px 0;font-size:13px
}
.row:first-of-type{border-top:0}
.row span{color:#888}
.actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:20px}
button{
 padding:9px 13px;border-radius:7px;
 border:1px solid #555;cursor:pointer;font-weight:600
}
.primary{background:#eee;color:#080808}
.secondary{background:#161616;color:#ddd}
#message{font-size:12px;color:#aaa;margin-top:15px;min-height:18px}
pre{
 font-size:11px;color:#999;white-space:pre-wrap;
 max-height:180px;overflow:auto
}
.note{font-size:11px;color:#777;line-height:1.5;margin-top:15px}

.portability-shell {
  margin: 24px;
  padding: 22px;
  border: 1px solid #343434;
  border-radius: 18px;
  background: #101010;
}

.portability-title,
.portability-card-head,
.dependency-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.portability-title h2,
.portability-card h3 {
  margin: 3px 0;
}

.portability-kicker {
  font-size: 11px;
  letter-spacing: 1.8px;
  color: #8d8d8d;
}

.portability-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
  margin-top: 18px;
}

.portability-card {
  padding: 18px;
  border: 1px solid #2e2e2e;
  border-radius: 14px;
  background: #151515;
}

.portability-status {
  margin-top: 18px;
  font-size: 20px;
  font-weight: 700;
}

.portability-detail,
.portability-note {
  margin-top: 8px;
  color: #a7a7a7;
  line-height: 1.5;
}

.portability-note {
  padding-top: 14px;
  border-top: 1px solid #292929;
}

.portability-actions {
  margin: 18px 0;
}

.state-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  display: inline-block;
  background: #666;
}

.state-dot.ready {
  background: #fff;
}

.state-dot.missing {
  background: #555;
}

.dependency-row {
  padding: 12px 0;
  border-bottom: 1px solid #292929;
}

.dependency-row:last-child {
  border-bottom: 0;
}

.dependency-name {
  font-weight: 650;
}

.dependency-state {
  margin-top: 3px;
  color: #999;
  font-size: 12px;
}

.dependency-ready {
  font-size: 12px;
  letter-spacing: .8px;
}


/* Progre global action progress */
#progre-progress {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9999;
  display: none;
  background: #111;
  border-bottom: 1px solid #333;
}

#progre-progress.visible {
  display: block;
}

#progre-progress-track {
  height: 4px;
  background: #222;
  overflow: hidden;
}

#progre-progress-bar {
  height: 100%;
  width: 0%;
  background: #fff;
  transition: width .25s ease;
}

#progre-progress.indeterminate #progre-progress-bar {
  width: 35%;
  animation: progre-progress-slide 1.1s ease-in-out infinite;
}

#progre-progress-label {
  padding: 7px 18px;
  font-size: 12px;
  letter-spacing: .04em;
  color: #ddd;
}

@keyframes progre-progress-slide {
  0%   { transform: translateX(-110%); }
  100% { transform: translateX(310%); }
}

</style>
</head>

<body>

<section class="portability-shell">
  <div class="portability-title">
    <div>
      <div class="portability-kicker">PROGRE PORTABILITY</div>
      <h2>Device &amp; Local Runtime</h2>
    </div>
    <button onclick="refreshPortability()">Refresh</button>
  </div>

  <div class="portability-grid">

    <div class="portability-card">
      <div class="portability-card-head">
        <div>
          <div class="portability-kicker">DEVICE</div>
          <h3>Detect AIPI</h3>
        </div>
        <span id="device-dot" class="state-dot"></span>
      </div>

      <div id="device-state" class="portability-status">
        Not scanned
      </div>

      <div id="device-detail" class="portability-detail">
        Connect an AIPI Lite or Progre by USB.
      </div>

      <div class="portability-actions">
        <button onclick="detectAipi()">Detect AIPI</button>
      </div>

      <div id="device-recovery" class="portability-note">
        Recovery and stock-firmware protection will appear here
        when compatible hardware is detected.
      </div>

      <div id="recovery-actions"
           class="portability-actions"
           style="display:none">
        <button id="backup-button"
                onclick="createRecoveryBackup()">
          Create Recovery Backup
        </button>
      </div>

      <div id="recovery-status"
           class="portability-detail"></div>

      <div id="recovery-preflight"
           class="portability-note">
        Install / restore safety state has not been checked yet.
      </div>

      <div id="destructive-actions"
           class="portability-actions"
           style="display:none">
        <button id="install-progre-button"
                onclick="installProgreOS()"
                disabled>
          Install Progre OS
        </button>

        <button id="restore-backup-button"
                onclick="restoreOriginalBackup()"
                disabled>
          Restore Verified Backup
        </button>
      </div>
    </div>

    <div class="portability-card">
      <div class="portability-card-head">
        <div>
          <div class="portability-kicker">HOST</div>
          <h3>Local Runtime</h3>
        </div>
      </div>

      <div id="runtime-list">
        Checking dependencies...
      </div>
    </div>

    <div class="portability-card">
      <div class="portability-card-head"><div><div class="portability-kicker">COMMISSIONING</div><h3>Wi-Fi &amp; Bridge</h3></div></div>
      <div class="portability-detail">Connect Progre by USB, scan networks, then point him at this computer's local Voice Bridge.</div>
      <div class="portability-actions"><button onclick="scanWifi()">Scan Wi-Fi</button><button onclick="reconnectProgre()">Reconnect</button></div>
      <label>Wi-Fi network</label><select id="wifi-ssid"><option value="">Scan first…</option></select>
      <label>Wi-Fi password</label><input id="wifi-password" type="password" autocomplete="new-password" placeholder="Not stored by Cockpit">
      <label>This computer / Bridge address</label><input id="bridge-host" placeholder="Detected automatically">
      <label>Bridge port</label><input id="bridge-port" type="number" value="8765" min="1" max="65535">
      <div class="portability-actions"><button class="primary" onclick="configureProgre()">Connect Progre</button><button onclick="rebootProgre()">Reboot</button></div>
      <div id="commission-message" class="portability-note">USB commissioning does not require rebuilding firmware after this protocol is installed.</div>
    </div>

  </div>
</section>



<div id="progre-progress">
  <div id="progre-progress-track">
    <div id="progre-progress-bar"></div>
  </div>
  <div id="progre-progress-label">Working…</div>
</div>

<header>
 <div class="brand">
  <div class="face">
   <div class="eye l"></div>
   <div class="eye r"></div>
   <div class="mouth"></div>
  </div>
  <div>
   <h1>PROGRE COCKPIT</h1>
   <div class="sub">Local companion control plane</div>
  </div>
 </div>
 <div id="badge" class="badge">Checking Bridge…</div>
</header>

<main>
<div class="grid">

<section class="card">
<h2>Intelligence</h2>

<label>Ollama model</label>
<select id="model"></select>

<label>Temperature</label>
<input id="temperature" type="range"
 min="0" max="2" step=".05">
<div id="temperatureV" class="value"></div>

<label>Maximum response tokens</label>
<input id="tokens" type="number"
 min="20" max="400" step="10">
</section>


<section class="card">
<h2>Voice Character</h2>

<label>Piper voice</label>
<select id="voice"></select>

<label>Pitch</label>
<input id="pitch" type="range"
 min="-6" max="6" step=".25">
<div id="pitchV" class="value"></div>

<label>Output volume</label>
<input id="volume" type="range"
 min=".05" max="2" step=".05">
<div id="volumeV" class="value"></div>
</section>


<section class="card">
<h2>Bridge</h2>

<div class="row">
 <span>Status</span>
 <strong id="bridge">—</strong>
</div>

<div class="row">
 <span>Voice Bridge</span>
 <strong>127.0.0.1:8765</strong>
</div>

<div class="row">
 <span>Cockpit</span>
 <strong>127.0.0.1:8766</strong>
</div>

<div class="row">
 <span>Control</span>
 <strong>LIVE</strong>
</div>

<div class="note">
The Cockpit writes configuration used by the Voice Bridge.
Closing this browser does not stop Progre.
</div>
</section>


<section class="card">
<h2>Control</h2>

<div class="actions">
 <button class="primary" onclick="save()">Save & Apply</button>
 <button class="secondary" onclick="load()">Reload</button>
 <button class="secondary" onclick="reset()">Defaults</button>
</div>

<div id="message"></div>

<label>Active configuration</label>
<pre id="cfg"></pre>
</section>

</div>
</main>


<script>
const $=id=>document.getElementById(id);

function options(el,values,current){
 el.innerHTML="";
 [...new Set([current,...values].filter(Boolean))]
 .forEach(v=>{
   const o=document.createElement("option");
   o.value=v;o.textContent=v;o.selected=v===current;
   el.appendChild(o);
 });
}

function labels(){
 $("pitchV").textContent=
   Number($("pitch").value).toFixed(2)+" semitones";

 $("volumeV").textContent=
   Number($("volume").value).toFixed(2)+" ×";

 $("temperatureV").textContent=
   Number($("temperature").value).toFixed(2);
}

function show(d){
 const c=d.config;

 options($("model"),d.models||[],c.model);
 options($("voice"),d.voices||[],c.voice);

 $("temperature").value=c.temperature;
 $("tokens").value=c.max_tokens;
 $("pitch").value=c.pitch_semitones;
 $("volume").value=c.volume;

 const online=d.bridge&&d.bridge.online;

 $("bridge").textContent=online?"ONLINE":"OFFLINE";
 $("badge").textContent=online?"● Bridge online":"○ Bridge offline";

 $("cfg").textContent=JSON.stringify(c,null,2);

 labels();
}

async function load(){
 $("message").textContent="Loading…";

 try{
   const r=await fetch("/api/status");
   show(await r.json());
   $("message").textContent="";
 }catch(e){
   $("message").textContent="Load failed: "+e;
 }
}

async function save(){
 const data={
   model:$("model").value,
   voice:$("voice").value,
   temperature:Number($("temperature").value),
   max_tokens:Number($("tokens").value),
   pitch_semitones:Number($("pitch").value),
   volume:Number($("volume").value)
 };

 $("message").textContent="Saving…";

 const r=await fetch("/api/config",{
   method:"POST",
   headers:{"Content-Type":"application/json"},
   body:JSON.stringify(data)
 });

 const j=await r.json();

 if(!r.ok){
   $("message").textContent=j.error||"Save failed";
   return;
 }

 $("cfg").textContent=JSON.stringify(j.config,null,2);
 $("message").textContent=
   "Saved — applies to the next conversation.";
}

async function reset(){
 await fetch("/api/reset",{method:"POST"});
 $("message").textContent="Defaults restored.";
 await load();
}

["pitch","volume","temperature"].forEach(
 id=>$(id).addEventListener("input",labels)
);

load();

setInterval(async()=>{
 try{
   const r=await fetch("/api/status");
   const d=await r.json();
   const online=d.bridge&&d.bridge.online;
   $("bridge").textContent=online?"ONLINE":"OFFLINE";
   $("badge").textContent=online?"● Bridge online":"○ Bridge offline";
 }catch(e){}
},5000);
</script>


<script>
function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}


let progreProgressTimer = null;

function actionProgressStart(label, percent=null) {
  const box = document.getElementById("progre-progress");
  const bar = document.getElementById("progre-progress-bar");
  const text = document.getElementById("progre-progress-label");

  if (!box || !bar || !text) return;

  clearTimeout(progreProgressTimer);

  text.textContent = label || "Working…";
  box.classList.add("visible");

  if (percent === null) {
    box.classList.add("indeterminate");
    bar.style.width = "35%";
  } else {
    box.classList.remove("indeterminate");
    bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  }
}

function actionProgressUpdate(label, percent=null) {
  actionProgressStart(label, percent);
}

function actionProgressFinish(label="Complete") {
  const box = document.getElementById("progre-progress");
  const bar = document.getElementById("progre-progress-bar");
  const text = document.getElementById("progre-progress-label");

  if (!box || !bar || !text) return;

  box.classList.remove("indeterminate");
  bar.style.width = "100%";
  text.textContent = label;

  clearTimeout(progreProgressTimer);

  progreProgressTimer = setTimeout(() => {
    box.classList.remove("visible");
    bar.style.width = "0%";
  }, 900);
}

function actionProgressFail(label="Action failed") {
  const box = document.getElementById("progre-progress");
  const text = document.getElementById("progre-progress-label");

  if (!box || !text) return;

  box.classList.remove("indeterminate");
  text.textContent = label;

  clearTimeout(progreProgressTimer);

  progreProgressTimer = setTimeout(() => {
    box.classList.remove("visible");
  }, 3000);
}

async function waitForInstall(component, label) {
  while (true) {
    await new Promise(resolve => setTimeout(resolve, 1000));

    const response = await fetch(`/api/install/status/${component}`);
    const data = await response.json();

    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Unable to read installer status.");
    }

    const job = data.job || {};
    const dependency = data.dependency || {};

    if (job.state === "ready" || dependency.ready) {
      actionProgressFinish(`${label} ready`);
      await loadRuntime();
      return;
    }

    if (job.state === "failed") {
      throw new Error(job.error || `${label} installation failed.`);
    }

    const percent =
      typeof job.progress === "number" && job.progress > 0
        ? job.progress
        : null;

    actionProgressUpdate(
      job.message || `Installing ${label}…`,
      percent
    );
  }
}

async function loadRuntime() {
  const target = document.getElementById("runtime-list");

  try {
    const response = await fetch("/api/runtime");
    const data = await response.json();

    const entries = Object.entries(data.dependencies || {});

    if (!entries.length) {
      target.innerHTML = "<div class='portability-detail'>No dependency definitions found.</div>";
      return;
    }

    target.innerHTML = entries.map(([key, item]) => {
      const ready = Boolean(item.ready);

      return `
        <div class="dependency-row">
          <div>
            <div class="dependency-name">${esc(item.label)}</div>
            <div class="dependency-state">
              ${ready ? "Installed / detected" : "Missing"}
            </div>
          </div>

          <div>
            ${
              ready
              ? `<span class="dependency-ready">READY</span>`
              : `<button onclick="installDependency('${esc(key)}')">Install</button>`
            }
          </div>
        </div>
      `;
    }).join("");

  } catch (error) {
    target.innerHTML =
      "<div class='portability-detail'>Runtime check failed.</div>";
  }
}

async function loadDevice() {
  try {
    const response = await fetch("/api/device");
    const data = await response.json();

    const detection = data.device?.detection || {};
    const state = detection.state || "not_scanned";

    document.getElementById("device-state").textContent =
      state === "not_scanned" ? "Not scanned" : state;

    document.getElementById("device-detail").textContent =
      detection.hardware
        ? `${detection.hardware} — ${detection.firmware || "Firmware unknown"}`
        : (detection.message || "Connect an AIPI Lite or Progre by USB.");

    document.getElementById("device-recovery").textContent =
      detection.message ||
      "Recovery and stock-firmware protection will appear here when compatible hardware is detected.";

    const recoveryActions =
      document.getElementById("recovery-actions");

    const recoveryStatus =
      document.getElementById("recovery-status");

    const backupButton =
      document.getElementById("backup-button");

    const backupCapable = [
      "stock_or_unknown",
      "compatible_detected",
      "port_busy_or_recovery",
      "progre_detected"
    ].includes(state);

    recoveryActions.style.display =
      backupCapable ? "flex" : "none";

    if (backupCapable) {
      try {
        const pf = await fetch("/api/device/recovery/preflight");
        const pd = await pf.json();

        const installReady = Boolean(pd.install?.ready);
        const restoreReady = Boolean(pd.restore?.ready);

        document.getElementById("recovery-preflight").textContent =
          `Install Progre OS: ${installReady ? "READY" : "BLOCKED"} — ` +
          `Restore Backup: ${restoreReady ? "READY" : "BLOCKED"}`;

        const destructive =
          document.getElementById("destructive-actions");

        const installButton =
          document.getElementById("install-progre-button");

        const restoreButton =
          document.getElementById("restore-backup-button");

        destructive.style.display = "flex";
        installButton.disabled = !installReady;
        restoreButton.disabled = !restoreReady;

        const backupKind =
          pd.restore?.backup_kind ||
          pd.restore?.recovery?.backup_kind ||
          "unknown";

        if (backupKind === "original_stock") {
          restoreButton.textContent =
            "Restore Original Stock Backup";
        } else if (backupKind === "progre_snapshot") {
          restoreButton.textContent =
            "Restore Progre Recovery Snapshot";
        } else {
          restoreButton.textContent =
            "Restore Verified Backup";
        }

      } catch (error) {
        document.getElementById("recovery-preflight").textContent =
          "Install / restore safety state unavailable.";
      }

      try {
        const rr = await fetch("/api/device/recovery");
        const rd = await rr.json();
        const recovery = rd.recovery || {};

        if (recovery.verified) {
          recoveryStatus.textContent =
            `Verified recovery backup available — ` +
            `${Number(recovery.size).toLocaleString()} bytes — ` +
            `SHA-256 ${String(recovery.sha256).slice(0, 12)}…`;

          backupButton.textContent =
            "Create New Recovery Backup";
        } else {
          recoveryStatus.textContent =
            state === "stock_or_unknown"
              ? "A verified full-flash backup is required before Progre OS can be installed."
              : "No verified recovery backup is currently recorded.";

          backupButton.textContent =
            "Create Recovery Backup";
        }
      } catch (error) {
        recoveryStatus.textContent =
          "Recovery status unavailable.";
      }
    } else {
      recoveryStatus.textContent = "";
    }

  } catch (error) {
    document.getElementById("device-state").textContent =
      "Device check unavailable";
  }
}

async function installProgreOS() {
  const phrase = prompt(
    "This will write Progre OS to the attached device.\n\n" +
    "A verified recovery backup is required.\n\n" +
    "Type INSTALL PROGRE OS exactly to continue."
  );

  if (phrase === null) return;

  if (phrase !== "INSTALL PROGRE OS") {
    alert("Confirmation did not match. Nothing was written.");
    return;
  }

  const installButton =
    document.getElementById("install-progre-button");

  const restoreButton =
    document.getElementById("restore-backup-button");

  installButton.disabled = true;
  restoreButton.disabled = true;

  actionProgressStart(
    "Installing Progre OS — do not disconnect the device…"
  );

  try {
    const response = await fetch(
      "/api/device/recovery/install",
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({confirmation: phrase})
      }
    );

    const data = await response.json();

    if (!response.ok || !data.ok) {
      throw new Error(
        data.message || data.error || "Installation failed."
      );
    }

    actionProgressFinish("Progre OS installation completed");
    alert("Progre OS installation completed successfully.");

  } catch (error) {
    actionProgressFail(
      `Installation failed: ${error.message || error}`
    );

    alert(
      "Installation failed. The recovery backup remains available.\n\n" +
      (error.message || error)
    );

  } finally {
    await loadDevice();
  }
}


async function restoreOriginalBackup() {
  const phrase = prompt(
    "This will overwrite the complete device flash with the verified " +
    "recovery image.\n\n" +
    "Type RESTORE VERIFIED BACKUP exactly to continue."
  );

  if (phrase === null) return;

  if (phrase !== "RESTORE VERIFIED BACKUP") {
    alert("Confirmation did not match. Nothing was written.");
    return;
  }

  const installButton =
    document.getElementById("install-progre-button");

  const restoreButton =
    document.getElementById("restore-backup-button");

  installButton.disabled = true;
  restoreButton.disabled = true;

  actionProgressStart(
    "Restoring verified recovery image — do not disconnect the device…"
  );

  try {
    const response = await fetch(
      "/api/device/recovery/restore",
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({confirmation: phrase})
      }
    );

    const data = await response.json();

    if (!response.ok || !data.ok) {
      throw new Error(
        data.message || data.error || "Restore failed."
      );
    }

    actionProgressFinish("Recovery image restored");
    alert("Verified recovery image restored successfully.");

  } catch (error) {
    actionProgressFail(
      `Restore failed: ${error.message || error}`
    );

    alert(
      "Restore failed. Review recovery status before retrying.\n\n" +
      (error.message || error)
    );

  } finally {
    await loadDevice();
  }
}


async function createRecoveryBackup() {
  const button = document.getElementById("backup-button");
  const status = document.getElementById("recovery-status");

  if (!confirm(
    "Create a complete recovery backup of the attached AIPI Lite? " +
    "This is read-only and may take a few minutes."
  )) return;

  if (button) {
    button.disabled = true;
    button.textContent = "Backing up…";
  }

  status.textContent =
    "Reading and verifying the complete 16 MiB device flash…";

  actionProgressStart(
    "Creating verified AIPI recovery backup…"
  );

  try {
    const response = await fetch(
      "/api/device/recovery/backup",
      {method: "POST"}
    );

    const data = await response.json();

    if (!response.ok || !data.ok || !data.verified) {
      throw new Error(
        data.message ||
        data.error ||
        "Recovery backup failed."
      );
    }

    status.textContent =
      `Verified recovery backup created — ` +
      `${Number(data.size).toLocaleString()} bytes — ` +
      `SHA-256 ${String(data.sha256).slice(0, 12)}…`;

    actionProgressFinish(
      "Recovery backup verified"
    );

    await loadDevice();

  } catch (error) {
    status.textContent =
      "Recovery backup failed: " +
      (error.message || error);

    actionProgressFail(
      `Recovery backup failed: ${error.message || error}`
    );

  } finally {
    if (button) {
      button.disabled = false;

      try {
        const response = await fetch("/api/device/recovery");
        const data = await response.json();

        button.textContent =
          data.recovery?.verified
            ? "Create New Recovery Backup"
            : "Create Recovery Backup";
      } catch (error) {
        button.textContent = "Create Recovery Backup";
      }
    }
  }
}

async function detectAipi() {
  const state = document.getElementById("device-state");
  const detail = document.getElementById("device-detail");

  state.textContent = "Scanning...";
  detail.textContent = "Checking attached USB hardware.";
  actionProgressStart("Detecting AIPI / Progre hardware…");

  try {
    const response = await fetch("/api/device/detect", {
      method: "POST"
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.message || data.error || `HTTP ${response.status}`
      );
    }

    await loadDevice();

    const detected = data.device?.detection || data.detection || {};
    const detectedState = detected.state || "device detected";

    actionProgressFinish(
      detectedState === "progre_detected"
        ? "Progre detected"
        : "Device detection complete"
    );

  } catch (error) {
    state.textContent = "Detection failed";
    detail.textContent = String(error);
    actionProgressFail(
      `Device detection failed: ${error.message || error}`
    );
  }
}

async function installDependency(component) {
  const labels = {
    whisper: "Whisper Speech Recognition",
    whisper_model: "Whisper Speech Model",
    ollama: "Ollama Local AI Runtime",
    ai_model: "Local AI Model",
    piper: "Piper Speech Engine",
    voice: "Progre Voice",
    ffmpeg: "FFmpeg Audio Processor"
  };

  const label = labels[component] || component;

  actionProgressStart(`Starting ${label}…`);

  try {
    const response = await fetch(`/api/install/${component}`, {
      method: "POST"
    });

    const data = await response.json();

    if (response.status === 409 &&
        data.error === "already_installing") {
      actionProgressUpdate(`${label} is already installing…`);
      await waitForInstall(component, label);
      return;
    }

    if (!response.ok) {
      throw new Error(
        data.message || data.error || "Installation failed."
      );
    }

    if (data.state === "ready") {
      actionProgressFinish(`${label} ready`);
      await loadRuntime();
      return;
    }

    actionProgressUpdate(`Installing ${label}…`);
    await waitForInstall(component, label);

  } catch (error) {
    console.error(error);
    actionProgressFail(`${label}: ${error.message || error}`);
  }
}

async function loadHostNetwork() {
  try { const d=await (await fetch("/api/host/network")).json(); if(d.ok){ document.getElementById("bridge-host").value=d.bridge_host; document.getElementById("bridge-port").value=d.bridge_port; } } catch(e) {}
}
async function scanWifi() {
  const msg = document.getElementById("commission-message");
  const sel = document.getElementById("wifi-ssid");

  msg.textContent = "Scanning from Progre…";
  actionProgressStart("Scanning Wi-Fi from Progre…");

  try {
    const response = await fetch("/api/device/wifi/scan", {
      method: "POST"
    });

    const data = await response.json();

    if (!response.ok || !data.ok) {
      throw new Error(
        data.message || data.error || "Wi-Fi scan failed"
      );
    }

    const seen = new Set();

    const nets = (data.networks || [])
      .filter(n =>
        n.ssid &&
        !seen.has(n.ssid) &&
        seen.add(n.ssid)
      )
      .sort((a, b) => b.rssi - a.rssi);

    sel.innerHTML = nets.map(n =>
      `<option value="${esc(n.ssid)}">` +
      `${esc(n.ssid)} (${n.rssi} dBm)</option>`
    ).join("");

    msg.textContent = `Found ${nets.length} network(s).`;

    actionProgressFinish(
      `Wi-Fi scan complete — ${nets.length} network(s)`
    );

  } catch (error) {
    msg.textContent =
      "Wi-Fi scan failed: " + (error.message || error);

    actionProgressFail(
      `Wi-Fi scan failed: ${error.message || error}`
    );
  }
}
async function configureProgre() {
  const msg = document.getElementById("commission-message");
  const passwordField = document.getElementById("wifi-password");
  const button =
    document.querySelector('button[onclick="configureProgre()"]');

  const body = {
    ssid: document.getElementById("wifi-ssid").value,
    password: passwordField.value,
    bridge_host: document.getElementById("bridge-host").value,
    bridge_port: Number(document.getElementById("bridge-port").value)
  };

  if (!body.ssid) {
    msg.textContent = "Select a Wi-Fi network first.";
    actionProgressFail("Select a Wi-Fi network first");
    return;
  }

  // Cockpit does not retain the Wi-Fi password after preparing the request.
  passwordField.value = "";

  if (button) {
    button.disabled = true;
    button.textContent = "Connecting…";
  }

  msg.textContent =
    `Saving ${body.ssid} credentials and Bridge settings. ` +
    "Waiting for Progre to actually join the network…";

  actionProgressStart(
    `Connecting Progre to ${body.ssid}…`
  );

  try {
    const response = await fetch("/api/device/configure", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)
    });

    const data = await response.json();

    if (data.ok && data.connected) {
      const bridgeState = data.bridge_online
        ? "Voice Bridge online."
        : "Wi-Fi connected; Voice Bridge is not responding yet.";

      msg.textContent =
        `READY — Progre connected to ${data.ssid}. ` +
        `Bridge ${data.bridge_host}:${data.bridge_port}. ${bridgeState}`;

      await loadDevice();

      actionProgressFinish(
        data.bridge_online
          ? `Progre ready on ${data.ssid}`
          : `Progre connected to ${data.ssid}`
      );

      return;
    }

    if (data.credentials_stored) {
      const state =
        data.device_status?.wifi_state ||
        "not connected";

      msg.textContent =
        `Credentials stored for ${body.ssid}, but Progre is currently ${state}. ` +
        (data.message || "Use Reconnect to try again.");

      await loadDevice();

      actionProgressFail(
        `Credentials saved — Progre is ${state}`
      );

      return;
    }

    throw new Error(
      data.message ||
      data.error ||
      `Configuration failed (HTTP ${response.status})`
    );

  } catch (error) {
    msg.textContent =
      "Configuration request failed: " +
      (error.message || error);

    actionProgressFail(
      `Connection failed: ${error.message || error}`
    );

  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "Connect Progre";
    }
  }
}
async function reconnectProgre() {
  const msg = document.getElementById("commission-message");

  actionProgressStart("Requesting Progre Wi-Fi reconnect…");

  try {
    const response = await fetch("/api/device/reconnect", {
      method: "POST"
    });

    const data = await response.json();

    if (!response.ok || !data.ok) {
      throw new Error(
        data.message || data.error || "Reconnect failed"
      );
    }

    msg.textContent = "Reconnect requested.";
    actionProgressFinish("Progre reconnect requested");

  } catch (error) {
    msg.textContent = String(error);
    actionProgressFail(
      `Reconnect failed: ${error.message || error}`
    );
  }
}
async function rebootProgre() {
  if (!confirm("Reboot Progre now?")) return;

  const msg = document.getElementById("commission-message");

  actionProgressStart("Rebooting Progre…");

  try {
    const response = await fetch("/api/device/reboot", {
      method: "POST"
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(
        data.message || data.error || `HTTP ${response.status}`
      );
    }

    msg.textContent =
      "Reboot requested. USB may disappear briefly.";

    actionProgressFinish("Progre reboot requested");

  } catch (error) {
    msg.textContent =
      "Reboot failed: " + (error.message || error);

    actionProgressFail(
      `Reboot failed: ${error.message || error}`
    );
  }
}

async function refreshPortability() {
  await Promise.all([
    loadRuntime(),
    loadDevice(),
    loadHostNetwork()
  ]);
}

refreshPortability();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    print("================================")
    print("         PROGRE COCKPIT")
    print("================================")
    print("http://127.0.0.1:8766")

    app.run(
        host="127.0.0.1",
        port=8766,
        debug=False,
        threaded=True,
    )
