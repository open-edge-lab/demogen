"""Validazione GLSL ES 3.00.

Due livelli: glslangValidator (se installato, veloce) e compilazione reale in
Chromium via harness (gate autorevole). Su Windows/Mac senza glslang basta il browser.
"""

from __future__ import annotations

import shutil
import subprocess


def have_glslang() -> bool:
    return shutil.which("glslangValidator") is not None


def validate_glslang(frag_src: str, timeout: float = 20.0) -> list[str]:
    """Ritorna la lista degli errori (vuota se ok). Richiede glslangValidator."""
    if not have_glslang():
        return []
    try:
        proc = subprocess.run(
            ["glslangValidator", "--stdin", "-S", "frag", "--glsl-version", "300", "es"],
            input=frag_src,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout + proc.stderr).strip()
        if proc.returncode == 0 and "ERROR" not in out:
            return []
        return [out] if out else ["errore sconosciuto"]
    except (OSError, subprocess.TimeoutExpired) as e:
        return [f"glslangValidator fallito: {e}"]


async def validate_in_browser(harness, frag_src: str) -> list[str]:
    """Compila lo shader dentro Chromium via l'harness; ritorna gli errori mappati."""
    res = await harness.load_fragment(frag_src)
    return [] if res["ok"] else res["errors"]


def check_source_rules(src: str) -> list[str]:
    """Regole del contratto §5.1 verificabili per tokenizzazione (no compilazione)."""
    errors: list[str] = []
    for banned in ("iMouse", "iDate", "iChannel", "iFrame", "iTimeDelta"):
        if banned in src:
            errors.append(f"uniform vietata: {banned}")
    # letterali interi usati inuites donde si aspetta float: euristica semplice
    for m in __import__("re").finditer(r"(?<![\w.])(\d+)(?![\w.])\s*[,;)]", src):
        errors.append(f"letterale intero nudo {m.group(1)} (usa {m.group(1)}.0): riga approx")
    return errors
