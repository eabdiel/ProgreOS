from pathlib import Path
import json
import sys
import urllib.request

from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bridge"
sys.path.insert(0, str(BRIDGE))

from progre_config import DEFAULT_CONFIG, load_config, save_config

app = Flask(__name__)

OLLAMA = "http://127.0.0.1:11434/api/tags"
HEALTH = "http://127.0.0.1:8765/health"

VOICE_DIR = (
    Path.home()
    / "Rend/experiments/autonomous-voice/runtime/piper/voices"
)


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
</style>
</head>

<body>

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

</body>
</html>
"""


if __name__ == "__main__":
    print("================================")
    print("         PROGRE COCKPIT")
    print("================================")
    print("http://127.0.0.1:8766")

    app.run(
        host="0.0.0.0",
        port=8766,
        debug=False,
        threaded=True,
    )
