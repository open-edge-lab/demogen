"""Controlli della pagina HTML della demo: start/pausa, stop, loop continuo, posizione."""

from __future__ import annotations

from pathlib import Path

import pytest

from demogen.bundle.build import PLAYER_DIST, build_payload_from_sources, write_bundle

SCENE = "void mainImage(out vec4 c, in vec2 p){ c = vec4(fract(iTime), p.x / iResolution.x, 0.5, 1.0); }\n"


def _html(tmp_path: Path, loop: bool = False) -> str:
    spec = {
        "name": "controlli",
        "bpm": 120,
        "beats_per_bar": 4,
        "loop": loop,
        # 1 battuta a 120 bpm = 2 s
        "scenes": [{"id": "s1", "start_bar": 0, "bars": 1, "transition_in": "cut", "transition_bars": 0}],
    }
    payload = build_payload_from_sources(spec, {"s1": SCENE}, do_minify=False)
    sizes = write_bundle(payload, tmp_path, "controlli")
    return Path(sizes["paths"]["html"]).read_text(encoding="utf-8")


def _state(page) -> dict:
    return page.evaluate(
        "() => { const p = window.__player; return {playing: p.isPlaying, t: p.currentTime(), loop: p.loop,"
        " ended: p.ended, bp: document.getElementById('bp').textContent,"
        " bl: document.getElementById('bl').getAttribute('aria-pressed')}; }"
    )


@pytest.mark.skipif(not (PLAYER_DIST / "demogen-player.min.js").exists(),
                    reason="dist missing: run npm run build first")
def test_testi_della_pagina_in_inglese(tmp_path: Path) -> None:
    html = _html(tmp_path)
    for text in ('<div id="hud">click to start</div>', 'title="Start / pause (Space)"',
                 'title="Stop: back to the start (S)"', 'title="Loop continuously when the demo ends (L)"',
                 'title="Click to seek"', "'loading…'", "'ERROR: '", "'❚❚ Pause'", "'▶ Restart'"):
        assert text in html, text


def test_controlli_start_stop_loop(harness, tmp_path: Path) -> None:
    page = harness.page
    page.set_content(_html(tmp_path))
    page.click("#hud")
    page.wait_for_function("() => window.__player && document.getElementById('bar').style.display === 'flex'")
    page.wait_for_timeout(300)
    s = _state(page)
    assert s["playing"] and s["bp"] == "❚❚ Pause" and s["loop"] is False and s["bl"] == "false"

    # Stop: in pausa e di nuovo all'inizio
    page.click("#bs")
    page.wait_for_timeout(100)
    s = _state(page)
    assert not s["playing"] and s["t"] == 0 and s["bp"] == "▶ Start"

    # Loop on: arrivata in fondo riparte da capo invece di fermarsi
    page.click("#bl")
    page.evaluate("() => window.__player.seek(1.8)")
    page.click("#bp")
    page.wait_for_timeout(700)
    s = _state(page)
    assert s["loop"] is True and s["bl"] == "true"
    assert s["playing"] and s["t"] < 1.0, s  # ha superato i 2 s ed è ripartita

    # Loop off (tasto L): a fine demo si ferma e il pulsante propone di ricominciare
    page.keyboard.press("l")
    page.evaluate("() => window.__player.seek(1.8)")
    page.wait_for_timeout(700)
    s = _state(page)
    assert s["loop"] is False and not s["playing"] and s["ended"] and s["bp"] == "▶ Restart", s

    # spazio: riparte dall'inizio
    page.keyboard.press("Space")
    page.wait_for_timeout(200)
    s = _state(page)
    assert s["playing"] and s["t"] < 0.6, s

    # S: stop
    page.keyboard.press("s")
    page.wait_for_timeout(100)
    s = _state(page)
    assert not s["playing"] and s["t"] == 0


def test_loop_del_payload_acceso_di_default(harness, tmp_path: Path) -> None:
    page = harness.page
    page.set_content(_html(tmp_path, loop=True))
    page.click("#hud")
    page.wait_for_function("() => window.__player && document.getElementById('bar').style.display === 'flex'")
    page.wait_for_timeout(200)
    s = _state(page)
    assert s["loop"] is True and s["bl"] == "true"


AUDIO = (
    "void mainAudio(out vec4 o, in float t){ float s = 0.3 * sin(6.2831853 * 220.0 * t);"
    " o = vec4(s, s, 0.0, 0.0); }\n"
)


def _html_audio(tmp_path: Path) -> str:
    spec = {"name": "suono", "bpm": 120, "beats_per_bar": 4, "loop": True,
            "scenes": [{"id": "s1", "start_bar": 0, "bars": 2, "transition_in": "cut", "transition_bars": 0}]}
    payload = build_payload_from_sources(spec, {"s1": SCENE}, do_minify=False, audio_src=AUDIO)
    sizes = write_bundle(payload, tmp_path, "suono")
    return Path(sizes["paths"]["html"]).read_text(encoding="utf-8")


def _audio_state(page) -> dict:
    return page.evaluate(
        "() => { const p = window.__player, bar = document.getElementById('bar');"
        " return {volume: p.volume, muted: p.muted, bm: document.getElementById('bm').textContent,"
        " pressed: document.getElementById('bm').getAttribute('aria-pressed'),"
        " slider: document.getElementById('bv').value, silent: bar.classList.contains('silent'),"
        " shown: getComputedStyle(document.getElementById('bm')).display !== 'none'}; }"
    )


def test_volume_e_mute_della_musica(harness, tmp_path: Path) -> None:
    page = harness.page
    page.set_content(_html_audio(tmp_path))
    page.evaluate("() => localStorage.clear()")
    page.click("#hud")
    page.wait_for_function("() => window.__player && document.getElementById('bar').style.display === 'flex'")
    s = _audio_state(page)
    assert s["shown"] and not s["silent"] and s["volume"] == 1 and not s["muted"] and s["bm"] == "♪ 100%"

    # M: muto e di nuovo con il suono
    page.keyboard.press("m")
    s = _audio_state(page)
    assert s["muted"] and s["pressed"] == "true" and s["bm"] == "♪ Muted"
    page.click("#bm")
    s = _audio_state(page)
    assert not s["muted"] and s["bm"] == "♪ 100%"

    # frecce: volume a passi del 10%, limitato a 0..1; il cursore segue
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    s = _audio_state(page)
    assert s["volume"] == pytest.approx(0.8) and s["slider"] == "0.8" and s["bm"] == "♪ 80%"
    for _ in range(4):
        page.keyboard.press("ArrowUp")
    assert _audio_state(page)["volume"] == 1

    # cursore: il valore scelto va al player e resta salvato per la prossima apertura
    page.evaluate("() => { const v = document.getElementById('bv'); v.value = '0.35';"
                  " v.dispatchEvent(new Event('input')); }")
    s = _audio_state(page)
    assert s["volume"] == pytest.approx(0.35) and s["bm"] == "♪ 35%"
    saved = page.evaluate("() => JSON.parse(localStorage.getItem('demogen.audio'))")
    assert saved == {"v": 0.35, "m": False}


def test_senza_musica_niente_controlli_audio(harness, tmp_path: Path) -> None:
    page = harness.page
    page.set_content(_html(tmp_path))
    page.click("#hud")
    page.wait_for_function("() => window.__player && document.getElementById('bar').style.display === 'flex'")
    s = _audio_state(page)
    assert s["silent"] and not s["shown"]


def test_il_canvas_segue_la_finestra_anche_in_pausa(harness, tmp_path: Path) -> None:
    page = harness.page
    page.set_viewport_size({"width": 640, "height": 360})
    page.set_content(_html(tmp_path, loop=True))
    page.click("#hud")
    page.wait_for_function("() => window.__player && document.getElementById('bar').style.display === 'flex'")
    page.click("#bp")  # pausa: nessun frame nuovo dal loop di riproduzione
    page.evaluate("() => { const p = window.__player, f = p.renderFrameAt.bind(p); window.__draws = 0;"
                  " p.renderFrameAt = (...a) => { window.__draws++; return f(...a); }; }")
    page.set_viewport_size({"width": 900, "height": 300})
    page.wait_for_function("() => document.getElementById('c').width === Math.floor(900 * devicePixelRatio)")
    size = page.evaluate("() => { const c = document.getElementById('c'); return [c.width, c.height]; }")
    dpr = page.evaluate("() => devicePixelRatio")
    assert size == [int(900 * dpr), int(300 * dpr)]
    assert not page.evaluate("() => window.__player.isPlaying")
    # il fotogramma è stato ridisegnato alla nuova dimensione: quello mostrato non è vuoto
    assert page.evaluate("() => window.__draws") >= 1
    import io

    import numpy as np
    from PIL import Image

    page.mouse.move(10, 10)  # il mouse fuori dalla barra: lo screenshot misura la scena
    shot = np.asarray(Image.open(io.BytesIO(page.screenshot())).convert("L"), dtype=np.float32) / 255
    assert shot.shape == (300, 900)
    assert shot[:200].mean() > 0.1, shot[:200].mean()  # parte alta, lontano dalla barra dei controlli


def test_barra_dentro_la_finestra_anche_se_stretta(harness, tmp_path: Path) -> None:
    page = harness.page
    page.set_viewport_size({"width": 480, "height": 640})
    html = _html_audio(tmp_path)
    assert '<link rel="icon" href="data:,">' in html  # nessuna richiesta a favicon.ico
    page.set_content(html)
    page.click("#hud")
    page.wait_for_function("() => window.__player && document.getElementById('bar').style.display === 'flex'")
    r = page.evaluate("() => { const r = document.getElementById('bar').getBoundingClientRect();"
                      " return [r.left, r.right, innerWidth]; }")
    assert r[0] >= 0 and r[1] <= r[2], r
    for el in ("#bp", "#bs", "#bl", "#bm", "#bv"):  # tutti i controlli visibili e cliccabili
        box = page.locator(el).bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= 480, (el, box)


def test_scena_retro_mantiene_le_proporzioni_in_una_finestra_verticale(harness, tmp_path: Path) -> None:
    # run reale: a 480x800 la scena retro (interna 320x180) veniva stirata e il gatto diventava alto e
    # stretto; ora resta 16:9 al centro con bande nere sopra e sotto
    import io

    import numpy as np
    from PIL import Image

    spec = {"name": "retro", "bpm": 120, "beats_per_bar": 4, "loop": True, "render": {"profile": "retro"},
            "scenes": [{"id": "s1", "start_bar": 0, "bars": 1, "transition_in": "cut", "transition_bars": 0}]}
    white = "void mainImage(out vec4 c, in vec2 p){ c = vec4(1.0); }\n"
    sizes = write_bundle(build_payload_from_sources(spec, {"s1": white}, do_minify=False), tmp_path, "retro")
    page = harness.page
    page.set_viewport_size({"width": 480, "height": 800})
    page.set_content(Path(sizes["paths"]["html"]).read_text(encoding="utf-8"))
    page.click("#hud")
    page.wait_for_function("() => window.__player && document.getElementById('bar').style.display === 'flex'")
    page.click("#bp")
    page.mouse.move(10, 10)
    shot = np.asarray(Image.open(io.BytesIO(page.screenshot())).convert("L"), dtype=np.float32) / 255
    rows = shot.mean(axis=1)
    lit = np.nonzero(rows > 0.5)[0]
    # 320x180 scalato a 480x270 e centrato in verticale: (800 - 270) / 2 = 265
    assert abs(lit.min() - 265) <= 2 and abs(lit.max() - 534) <= 2, (lit.min(), lit.max())
    assert rows[:250].max() < 0.05 and rows[550:700].max() < 0.05
    assert shot[300:500].min() > 0.9  # tutta la larghezza: nessuna banda laterale
