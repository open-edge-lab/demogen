"""Server MCP (demogen/mcp_server.py): un agente esterno scrive i file, demogen compila, rende, misura.

Il client MCP è quello dell'SDK collegato in-process (`Client(server)`): stesso protocollo di un
agente vero su stdio, senza sottoprocesso. Il progetto dell'agente vive in una cartella temporanea.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcp import Client

from demogen.mcp_server import build_server, library_reference, render_guide

ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "examples" / "common.glsl").read_text(encoding="utf-8")
BROKEN = """// scena dell'agente
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec3 col = vec3(0.2) * missingVar;
    fragColor = vec4(finalize(col, fragCoord / iResolution.xy), 1.0);
}
"""
FIXED = """// scena dell'agente
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = fragCoord / iResolution.xy;
    vec3 col = cosPalette(uv.x + iTime * 0.1, vec3(0.5), vec3(0.5), vec3(1.0), vec3(0.0, 0.33, 0.67));
    fragColor = vec4(finalize(col, uv), 1.0);
}
"""
TIMELINE = {
    "name": "agent-demo", "bpm": 120, "beats_per_bar": 4, "loop": False, "common": "style.glsl",
    "render": {"profile": "modern"}, "quality": {"target_fps": 60, "min_scale": 0.5},
    "scenes": [{"id": "s1", "src": "shaders/s1.glsl", "start_bar": 0, "bars": 2,
                "transition_in": "cut", "transition_bars": 0}],
}


def _text(res) -> str:
    return "\n".join(c.text for c in res.content if c.type == "text")


def _images(res) -> list:
    return [c for c in res.content if c.type == "image"]


def test_agente_esterno_dal_codice_sbagliato_al_bundle(tmp_path: Path) -> None:
    (tmp_path / "style.glsl").write_text(STYLE, encoding="utf-8")
    (tmp_path / "shaders").mkdir()
    scene = tmp_path / "shaders" / "s1.glsl"
    scene.write_text(BROKEN, encoding="utf-8")
    (tmp_path / "demo.timeline.json").write_text(json.dumps(TIMELINE), encoding="utf-8")
    (tmp_path.parent / "secret.glsl").write_text(FIXED, encoding="utf-8")
    server, renderer = build_server(tmp_path, gpu="swiftshader")

    async def agent() -> None:
        async with Client(server) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert names == {"guide", "glsl_library", "validate", "render", "render_still", "inspect",
                             "verify_math", "bundle"}

            # errore con file e riga della scena (non del fragment intero)
            res = json.loads(_text(await c.call_tool("validate", {"path": "demo.timeline.json"})))
            assert res["ok"] is False
            assert res["errors"][0].startswith("shaders/s1.glsl:3:") and "missingVar" in res["errors"][0]

            scene.write_text(FIXED, encoding="utf-8")
            res = json.loads(_text(await c.call_tool("validate", {"path": "demo.timeline.json"})))
            assert res == {**res, "ok": True, "errors": []}

            res = await c.call_tool("render", {"path": "shaders/s1.glsl", "times": [0.5, 2.0], "width": 160,
                                               "height": 90})
            assert not res.is_error and len(_images(res)) == 1 and _images(res)[0].mime_type == "image/jpeg"
            assert sorted(p.name for p in (tmp_path / "out" / "mcp" / "render_s1").iterdir()) == \
                ["t0.5s.png", "t2s.png"]

            # immagine fissa: PNG e riepilogo su disco, anteprima intera + ritaglio 1:1, gate
            res = await c.call_tool("render_still", {"path": "shaders/s1.glsl", "time": 1.0, "width": 200,
                                                     "height": 120, "spp": 2, "tile": 64, "crop": [0.9, 0.1]})
            summary = json.loads(_text(res))
            assert not res.is_error and len(_images(res)) == 2, _text(res)
            assert summary["tiles"] == 8 and summary["issues"] == [] and summary["crop_box"] == [0, 0, 200, 120]
            assert (tmp_path / summary["png"]).exists()
            res = await c.call_tool("render_still", {"path": "shaders/s1.glsl", "spp": 0})
            assert res.is_error and "spp" in _text(res)

            res = await c.call_tool("inspect", {"path": "demo.timeline.json", "frames": 4})
            summary = json.loads(_text(res))
            assert not res.is_error and summary["blockers"] == 0 and summary["flash"]["passed"]
            assert summary["video"]["nan_ratio"] == 0 and len(_images(res)) == 1
            assert (tmp_path / "out" / "mcp" / "inspect_demo" / "issues.json").exists()

            res = json.loads(_text(await c.call_tool("bundle", {"path": "demo.timeline.json"})))
            assert res["demo"] == "out/mcp/bundle/agent-demo.demo" and (tmp_path / res["html"]).exists()

            # fuori dalla radice dell'agente non si legge niente: né il percorso passato alla tool né i
            # file a cui rimanda una timeline (scena, style, audio), il cui testo tornerebbe negli errori
            # i percorsi di rete (UNC) si scartano come stringhe: resolve() su Windows aprirebbe una
            # connessione SMB e manderebbe le credenziali NTLM a quel server
            for path in ("../secret.glsl", str(tmp_path.parent / "secret.glsl"),
                         "\\\\attacker.invalid\\share\\x.glsl", "//attacker.invalid/share/x.glsl"):
                res = await c.call_tool("validate", {"path": path})
                assert res.is_error and "outside the workspace root" in _text(res)
            for key, value in (("src", "../../secret.glsl"), ("common", "../secret.glsl"),
                               ("audio", str(tmp_path.parent / "secret.glsl")),
                               ("src", str(tmp_path / "shaders" / "s1.glsl")),  # assoluti mai, neanche dentro
                               ("src", "\\\\attacker.invalid\\share\\x.glsl"),
                               ("common", "//attacker.invalid/share/style.glsl")):
                evil = json.loads(json.dumps(TIMELINE))
                if key == "src":
                    evil["scenes"][0]["src"] = value
                else:
                    evil[key] = value
                (tmp_path / "evil.timeline.json").write_text(json.dumps(evil), encoding="utf-8")
                for tool in ("validate", "render", "inspect", "bundle"):
                    res = await c.call_tool(tool, {"path": "evil.timeline.json"})
                    assert res.is_error and "outside the workspace root" in _text(res), (key, tool)
            # uno shader sciolto nella radice non prende il common.glsl della cartella sopra
            (tmp_path.parent / "common.glsl").write_text("#error secret style\n", encoding="utf-8")
            (tmp_path / "loose.glsl").write_text(FIXED, encoding="utf-8")
            res = json.loads(_text(await c.call_tool("validate", {"path": "loose.glsl"})))
            assert res["ok"] is True, res

            # oracolo: un SDF esatto passa e diventa GLSL, uno scalato ×2 no
            res = json.loads(_text(await c.call_tool("verify_math", {"requests": [
                {"id": "sdf_circle", "kind": "sdf", "inputs": {"x": "float", "y": "float"},
                 "expr": "len2(x, y) - 1.0", "claim": {"domain": [[-2, 2], [-2, 2]]}},
                {"id": "sdf_wrong", "kind": "sdf", "inputs": {"x": "float", "y": "float"},
                 "expr": "2.0 * (len2(x, y) - 1.0)", "claim": {"domain": [[-2, 2], [-2, 2]]}},
            ]})))
            status = {r["id"]: r["status"] for r in res["results"]}
            assert status == {"sdf_circle": "accepted", "sdf_wrong": "rejected"}
            assert "float sdf_circle(float x, float y)" in res["results"][0]["glsl"]

    try:
        asyncio.run(agent())
    finally:
        renderer.close()


def test_shader_in_linea_e_guida() -> None:
    # niente file: lo shader passa come testo, lo style è quello degli esempi
    server, renderer = build_server(ROOT, gpu="swiftshader")

    async def agent() -> None:
        async with Client(server) as c:
            res = json.loads(_text(await c.call_tool("validate", {"shader": BROKEN})))
            assert res["ok"] is False and res["errors"][0].startswith("(shader):3:")
            res = await c.call_tool("render", {"shader": FIXED, "times": [1.0], "width": 64, "height": 36})
            assert not res.is_error and len(_images(res)) == 1

    try:
        asyncio.run(agent())
    finally:
        renderer.close()
    guide = render_guide()
    assert "mainImage" in guide and "finalize" in guide and "## Gates" in guide
    assert "Response format" not in guide  # l'envelope è della pipeline LLM, non dell'agente esterno
    assert "### `sdBox`" in library_reference("sdbox") and "fbm" not in library_reference("sdbox")
