"""Build del bundle: da timeline.json + shader + common → .demo + .html standalone."""

from __future__ import annotations

import gzip
import html as html_mod
import json
from pathlib import Path

from ..glsl.minify import minify
from ..glsl.preprocessor import preprocess
from ..glsl.treeshake import load_library, shared_common_conflicts, treeshake
from ..project.store import slugify
from ..spec.models import DemoPayloadSpec

LIB_DIR = Path(__file__).resolve().parents[1] / "glsl" / "lib"
PLAYER_DIST = Path(__file__).resolve().parents[2] / "player" / "dist"


def build_payload_from_sources(
    spec: dict,
    scenes_src: dict[str, str],
    style_src: str = "",
    do_minify: bool = True,
    math_srcs: dict[str, str] | None = None,
    audio_src: str = "",
) -> dict:
    """Payload .demo da sorgenti in memoria (pipeline).

    `math_srcs` (Fase 6, oracolo matematico): funzioni GLSL verificate per scena,
    concatenate davanti allo shader della scena.
    """
    bpm = float(spec["bpm"])
    bpb = int(spec.get("beats_per_bar", 4))
    scenes_spec = spec["scenes"]
    lib = load_library(LIB_DIR)
    math_srcs = math_srcs or {}
    merged = {
        k: (math_srcs[k] + "\n" + v if k in math_srcs else v)
        for k, v in scenes_src.items()
    }
    conflicts = shared_common_conflicts(merged, style_src, lib)
    if conflicts:
        raise ValueError("bundle: " + "; ".join(conflicts))
    entry = "\n".join(merged.values()) + "\n" + style_src
    common = treeshake(entry, lib) + "\n" + style_src
    if audio_src:
        # la lib serve anche allo shader audio: treeshake dedicato e payload audio self-contained
        audio_src = treeshake(audio_src, lib) + "\n" + audio_src
    if do_minify:
        common = minify(common)
        merged = {k: minify(v) for k, v in merged.items()}
        if audio_src:
            audio_src = minify(audio_src)

    return _finalize_payload(spec, bpm, bpb, scenes_spec, merged, common, audio_src)


def build_payload(spec: dict, base_dir: Path, do_minify: bool = True) -> dict:
    """Costruisce il payload .demo da una spec timeline (JSON) + file shader."""
    scenes_spec = spec["scenes"]
    scenes_src: dict[str, str] = {}
    for s in scenes_spec:
        scenes_src[s["id"]] = (base_dir / s["src"]).read_text(encoding="utf-8")
    style_path = spec.get("common")
    style_src = ""
    if style_path:
        style_text = (base_dir / style_path).read_text(encoding="utf-8")
        style_src, _ = preprocess(style_text, base_dir=base_dir)
    audio_src = ""
    audio_path = spec.get("audio")
    if audio_path:
        audio_src, _ = preprocess((base_dir / audio_path).read_text(encoding="utf-8"), base_dir=base_dir)
    return build_payload_from_sources(spec, scenes_src, style_src, do_minify, audio_src=audio_src)


def _finalize_payload(spec: dict, bpm: float, bpb: int, scenes_spec: list,
                      scenes_src: dict[str, str], common: str, audio_src: str = "") -> dict:
    last = scenes_spec[-1]
    duration_s = (last["start_bar"] + last["bars"]) * bpb * 60.0 / bpm
    payload = {
        "format": "demogen/1",
        "meta": {
            "title": spec.get("name", "demogen demo"),
            "duration_s": duration_s,
            "loop": bool(spec.get("loop", False)),
            "bpm": bpm,
            "beats_per_bar": bpb,
        },
        "timeline": {
            "bpm": bpm,
            "beats_per_bar": bpb,
            "scenes": [
                {
                    "id": s["id"],
                    "start_bar": float(s["start_bar"]),
                    "bars": float(s["bars"]),
                    "transition_in": s.get("transition_in", "cut"),
                    "transition_bars": float(s.get("transition_bars", 0)),
                }
                for s in scenes_spec
            ],
        },
        "common": common,
        "scenes": scenes_src,
        "render": spec.get("render", {"profile": "modern"}),
        "text": spec.get("text"),
        "post": spec.get("post", {}),
        "quality": spec.get("quality", {"min_scale": 0.25, "target_fps": 60}),
    }
    if audio_src:
        payload["audio"] = audio_src
    DemoPayloadSpec.model_validate(payload)  # validazione completa lato Python
    return payload


# Avvio del bundle al primo click:
# - l'AudioContext nasce e fa resume() DENTRO il gesto (policy autoplay), poi passa al Player:
#   i listener di sblocco del Player arriverebbero dopo la compilazione, a click già finito;
# - l'HUD resta su "loading…" e mostra gli errori di costruttore e load();
# - barra dei controlli: Start/Pause, Stop (torna all'inizio), Loop continuo on/off, posizione
#   cliccabile, tempo, e se la demo ha musica mute e volume (ricordati in localStorage); si nasconde
#   mentre la demo va e ricompare muovendo il mouse;
# - tasti: spazio = start/pausa, S = stop, L = loop, M = mute, frecce su/giù = volume ±10%;
# - il canvas segue la finestra: il Player ridimensiona il buffer e ridisegna anche in pausa.
_BOOT_JS = """
const $=id=>document.getElementById(id);
const hud=$('hud'),bar=$('bar'),bp=$('bp'),bs=$('bs'),bl=$('bl'),pos=$('pos'),fill=$('fill'),tm=$('tm');
const bm=$('bm'),bv=$('bv'),KEY='demogen.audio';
let vol=1,mut=false;
try{const s=JSON.parse(localStorage.getItem(KEY)||'{}');
  if(typeof s.v==='number')vol=Math.max(0,Math.min(1,s.v));mut=!!s.m;}catch(e){}
const setVol=(v,m)=>{vol=Math.round(Math.max(0,Math.min(1,v))*100)/100;mut=m;
  if(p){p.volume=vol;p.muted=mut;}
  bv.value=String(vol);bm.setAttribute('aria-pressed',String(mut));
  bm.textContent=mut||vol===0?'♪ Muted':'♪ '+Math.round(vol*100)+'%';
  try{localStorage.setItem(KEY,JSON.stringify({v:vol,m:mut}));}catch(e){}};
const fail=e=>{hud.style.display='flex';hud.textContent='ERROR: '+((e&&e.message)||e);};
const two=n=>String(n).padStart(2,'0');
const mmss=t=>{t=Math.max(0,Math.floor(t));return two(Math.floor(t/60))+':'+two(t%60);};
let p=null,moved=0,shown='';
hud.addEventListener('click',()=>{
  hud.textContent='loading…';let ac;
  try{const AC=window.AudioContext||window.webkitAudioContext;if(AC&&PAYLOAD.audio){ac=new AC();ac.resume();}}catch(e){}
  try{p=new demogenPlayer.Player($('c'),PAYLOAD,{autoPlay:true,audioContext:ac,volume:vol,muted:mut});}
  catch(e){fail(e);return;}
  window.__player=p;
  p.load().then(()=>{hud.style.display='none';bar.style.display='flex';bar.classList.toggle('silent',!p.hasAudio);
    setVol(vol,mut);moved=performance.now();requestAnimationFrame(ui);}).catch(fail);
},{once:true});
const toggle=()=>{if(p)p.isPlaying?p.pause():p.play();};
const stop=()=>{if(p)p.stop();};
const loop=()=>{if(p)p.setLoop(!p.loop);};
const mute=()=>setVol(mut&&vol===0?0.5:vol,!(mut||vol===0));
bp.onclick=toggle;bs.onclick=stop;bl.onclick=loop;bm.onclick=mute;
bv.oninput=()=>setVol(+bv.value,false);
pos.onclick=e=>{if(!p)return;const r=pos.getBoundingClientRect();
  p.seek(Math.max(0,Math.min(1,(e.clientX-r.left)/r.width))*p.durationS);};
addEventListener('keydown',e=>{if(!p)return;
  if(e.code==='Space'){e.preventDefault();toggle();}else if(e.code==='KeyS')stop();else if(e.code==='KeyL')loop();
  else if(e.code==='KeyM')mute();
  else if(e.code==='ArrowUp'||e.code==='ArrowDown'){e.preventDefault();
    setVol(vol+(e.code==='ArrowUp'?.1:-.1),false);}});
addEventListener('pointermove',()=>{moved=performance.now();});
function ui(now){
  const t=p.currentTime(),d=p.durationS;
  const label=p.isPlaying?'❚❚ Pause':(p.ended?'▶ Restart':'▶ Start');
  const s=label+'|'+p.loop+'|'+mmss(t)+' / '+mmss(d);
  if(s!==shown){shown=s;bp.textContent=label;bl.setAttribute('aria-pressed',String(p.loop));
    bl.textContent='⟳ Loop '+(p.loop?'on':'off');tm.textContent=mmss(t)+' / '+mmss(d);}
  fill.style.width=(d>0?Math.min(100,t/d*100):0)+'%';
  document.body.classList.toggle('idle',p.isPlaying&&now-moved>2500);
  requestAnimationFrame(ui);
}
"""

_STYLE = (
    "html,body{margin:0;height:100%;background:#000;overflow:hidden}"
    "canvas{position:fixed;inset:0;width:100%;height:100%;display:block}"
    "#hud{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;"
    "color:#eee;font:14px monospace;cursor:pointer}"
    "#bar{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);display:none;align-items:center;"
    "gap:10px;padding:8px 12px;background:rgba(8,8,18,.8);border:1px solid #b14aed;border-radius:6px;"
    "font:13px monospace;color:#d8e2ff;transition:opacity .4s;user-select:none;"
    "width:max-content;white-space:nowrap;max-width:calc(100vw - 20px);box-sizing:border-box;"
    "flex-wrap:wrap;justify-content:center;row-gap:8px}"
    "#bar button{font:inherit;color:inherit;background:#15152a;border:1px solid #3d3d66;border-radius:4px;"
    "padding:4px 10px;cursor:pointer}"
    "#bar button:hover{border-color:#05d9e8}"
    "#bar button[aria-pressed=true]{border-color:#39ff14;color:#39ff14}"
    "#pos{width:180px;height:6px;background:#2a2a44;border-radius:3px;cursor:pointer;position:relative}"
    "#fill{position:absolute;left:0;top:0;bottom:0;width:0;border-radius:3px;"
    "background:linear-gradient(90deg,#f72585,#05d9e8)}"
    "#bm[aria-pressed=true]{border-color:#ff2a6d;color:#ff2a6d}"
    "#bv{width:90px;accent-color:#05d9e8;cursor:pointer}"
    "#bar.silent #bm,#bar.silent #bv{display:none}"
    "body.idle #bar{opacity:0}body.idle{cursor:none}"
)

_CONTROLS = (
    '<div id="bar">'
    '<button id="bp" title="Start / pause (Space)">▶ Start</button>'
    '<button id="bs" title="Stop: back to the start (S)">■ Stop</button>'
    '<button id="bl" title="Loop continuously when the demo ends (L)" aria-pressed="false">⟳ Loop off</button>'
    '<div id="pos" title="Click to seek"><div id="fill"></div></div>'
    '<span id="tm">00:00 / 00:00</span>'
    '<button id="bm" title="Mute / unmute the music (M)" aria-pressed="false">♪ 100%</button>'
    '<input id="bv" type="range" min="0" max="1" step="0.05" value="1" title="Music volume (up / down arrows)"'
    ' aria-label="Music volume">'
    "</div>"
)


def script_json(obj: object) -> str:
    """JSON sicuro dentro <script>: `<` → `\\u003c` neutralizza `</script>` e `<!--`.

    Un `<` può comparire solo dentro le stringhe JSON, dove `\\u003c` è equivalente
    sia in JSON sia in JS.
    """
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")


def write_bundle(payload: dict, out_dir: Path, name: str) -> dict:
    """Scrive out/<name>.demo e out/<name>.html (standalone, no rete). Ritorna le taglie.

    `name` può venire dall'LLM: diventa uno slug, quindi niente `/`, `..` o `:`.
    """
    name = slugify(name)
    out_dir.mkdir(parents=True, exist_ok=True)
    demo_path = out_dir / f"{name}.demo"
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    demo_path.write_bytes(raw)

    player_js = (PLAYER_DIST / "demogen-player.min.js").read_text(encoding="utf-8")
    title = html_mod.escape(str(payload["meta"]["title"]))
    html = (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
        f"<title>{title}</title>"
        f"<link rel=\"icon\" href=\"data:,\"><style>{_STYLE}</style></head><body>"
        f"<canvas id=\"c\"></canvas><div id=\"hud\">click to start</div>{_CONTROLS}"
        f"<script>{player_js}</script>"
        f"<script>const PAYLOAD={script_json(payload)};</script>"
        f"<script>{_BOOT_JS}</script></body></html>"
    )
    html_path = out_dir / f"{name}.html"
    html_path.write_text(html, encoding="utf-8")

    player_gz = len(gzip.compress(player_js.encode(), 9))
    return {
        "demo": {"raw": len(raw), "gzip": len(gzip.compress(raw, 9))},
        "html": {"raw": html_path.stat().st_size},
        "player_core_gz": player_gz,
        "paths": {"demo": str(demo_path), "html": str(html_path)},
    }
