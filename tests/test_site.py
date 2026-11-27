"""Sito per GitHub Pages (scripts/build-site.mts): galleria + pagine di examples/web con il player accanto."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "player" / "dist"


@pytest.mark.skipif(shutil.which("node") is None, reason="node non installato")
@pytest.mark.skipif(not (DIST / "demogen-player.min.js").exists(), reason="player non compilato (npm run build)")
def test_sito_galleria_e_pagine_con_il_player_accanto(tmp_path):
    out = tmp_path / "site"
    r = subprocess.run(["node", str(ROOT / "scripts" / "build-site.mts"), str(out)],
                       cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr

    assert (out / "player" / "demogen-player.min.js").read_bytes() == (DIST / "demogen-player.min.js").read_bytes()
    assert (out / "player" / "demogen-player.esm.js").exists()
    # la demo M1 (index.html nel repo) cede il posto alla galleria
    assert (out / "m1.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    gallery = (out / "index.html").read_text(encoding="utf-8")

    pages = sorted(p.name for p in (ROOT / "examples" / "web").glob("*.html"))
    for name in pages:
        site_name = "m1.html" if name == "index.html" else name
        html = (out / site_name).read_text(encoding="utf-8")
        assert "../../" not in html, f"{site_name} punta fuori dal sito"
        assert f'href="{site_name}"' in gallery, f"{site_name} manca dalla galleria"
        # ogni script locale esiste nel sito
        for src in re.findall(r'<script[^>]*\ssrc="([^"]+)"', html):
            if not src.startswith(("http:", "https:", "data:")):
                assert (out / src).exists(), f"{site_name}: {src} non c'è"
    # sorgenti e documentazione restano fuori
    assert not (out / "README.md").exists()
