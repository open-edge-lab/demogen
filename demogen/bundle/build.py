"""Build del bundle: da timeline.json + shader + common → .demo + .html standalone."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from ..glsl.minify import minify
from ..glsl.preprocessor import preprocess
from ..glsl.treeshake import load_library, treeshake
from ..spec.models import DemoPayloadSpec

LIB_DIR = Path(__file__).resolve().parents[1] / "glsl" / "lib"
PLAYER_DIST = Path(__file__).resolve().parents[2] / "player" / "dist"


def build_payload_from_sources(
    spec: dict, scenes_src: dict[str, str], style_src: str = "", do_minify: bool = True
) -> dict:
    """Payload .demo da sorgenti in memoria (pipeline)."""
    bpm = float(spec["bpm"])
    bpb = int(spec.get("beats_per_bar", 4))
    scenes_spec = spec["scenes"]
    lib = load_library(LIB_DIR)
    entry = "\n".join(scenes_src.values()) + "\n" + style_src
    common = treeshake(entry, lib) + "\n" + style_src
    if do_minify:
        common = minify(common)
        scenes_src = {k: minify(v) for k, v in scenes_src.items()}

    return _finalize_payload(spec, bpm, bpb, scenes_spec, scenes_src, common)


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
    return build_payload_from_sources(spec, scenes_src, style_src, do_minify)


def _finalize_payload(spec: dict, bpm: float, bpb: int, scenes_spec: list,
                      scenes_src: dict[str, str], common: str) -> dict:
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
        "quality": spec.get("quality", {"min_scale": 0.5, "target_fps": 60}),
    }
    DemoPayloadSpec.model_validate(payload)  # validazione completa lato Python
    return payload


def write_bundle(payload: dict, out_dir: Path, name: str) -> dict:
    """Scrive out/<name>.demo e out/<name>.html (standalone, no rete). Ritorna le taglie."""
    out_dir.mkdir(parents=True, exist_ok=True)
    demo_path = out_dir / f"{name}.demo"
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    demo_path.write_bytes(raw)

    player_js = (PLAYER_DIST / "demogen-player.min.js").read_text(encoding="utf-8")
    html = (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
        f"<title>{payload['meta']['title']}</title>"
        "<style>html,body{margin:0;height:100%;background:#000}"
        "canvas{width:100vw;height:100vh;display:block}"
        "#hud{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;"
        "color:#eee;font:14px monospace;cursor:pointer}</style></head><body>"
        "<canvas id=\"c\"></canvas><div id=\"hud\">click per avviare</div>"
        f"<script>{player_js}</script>"
        f"<script>const PAYLOAD={json.dumps(payload, ensure_ascii=False)};</script>"
        "<script>"
        "document.getElementById('hud').addEventListener('click',()=>{"
        "document.getElementById('hud').remove();"
        "const p=new demogenPlayer.Player(document.getElementById('c'),PAYLOAD,{autoPlay:true});"
        "p.load();window.__player=p;},{once:true});"
        "</script></body></html>"
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
