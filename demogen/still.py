"""Immagini fisse ad alta risoluzione con il motore realtime.

L'immagine intera si divide in tile; per ogni tile il browser somma `spp` campioni sub-pixel in un
FBO float (player/src/still.ts) e Python ricompone il PNG. Un campione costa quanto un frame realtime
della stessa area, quindi nessun comando GPU dura abbastanza da far scattare il watchdog, qualunque
sia la dimensione finale o il numero di campioni.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .engine import CompileFailed

MAX_SIDE = 32768
MAX_PIXELS = 16384 * 16384  # ~805 MB di RGB in memoria: oltre serve un PNG scritto a strisce
MAX_SPP = 4096
MAX_QUALITY = 4.0
WATCHDOG_WARN_MS = 1000.0  # un campione di un tile oltre questo è a metà strada dal TDR di Windows


@dataclass
class TileStat:
    x: int  # angolo in alto a sinistra, coordinate immagine
    y: int
    w: int
    h: int
    ms_total: float
    ms_max: float  # campione più lento: è lui a rischiare il watchdog


@dataclass
class StillResult:
    image: np.ndarray  # (H, W, 3) uint8
    renderer: str
    t: float
    spp: int
    quality: float
    tile: int
    wall_ms: float
    tiles: list[TileStat] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        per_sample = [s.ms_total / self.spp for s in self.tiles]
        h, w = self.image.shape[:2]
        return {
            "width": w,
            "height": h,
            "t": self.t,
            "spp": self.spp,
            "quality": self.quality,
            "tile": self.tile,
            "tiles": len(self.tiles),
            "renderer": self.renderer,
            "wall_ms": round(self.wall_ms, 1),
            "gpu_ms": round(sum(s.ms_total for s in self.tiles), 1),
            "ms_per_tile_sample_mean": round(float(np.mean(per_sample)), 3) if per_sample else 0.0,
            "ms_per_tile_sample_max": round(max((s.ms_max for s in self.tiles), default=0.0), 3),
            "warnings": self.warnings,
        }


def validate_still_args(width: int, height: int, spp: int, tile: int, quality: float) -> None:
    """Limiti prima di aprire il browser: messaggi per l'utente (inglese)."""
    if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
        raise ValueError(f"width and height must be between 1 and {MAX_SIDE}")
    if width * height > MAX_PIXELS:
        raise ValueError(f"image too large: {width}x{height} > {MAX_PIXELS} pixels")
    if not 1 <= spp <= MAX_SPP:
        raise ValueError(f"spp must be between 1 and {MAX_SPP}")
    if not 16 <= tile <= 4096:
        raise ValueError("tile must be between 16 and 4096")
    if not 0.0 <= quality <= MAX_QUALITY:
        raise ValueError(f"quality must be between 0 and {MAX_QUALITY}")


def render_still(h, payload: dict, *, t: float, width: int, height: int, spp: int = 16, tile: int = 1024,
                 quality: float = 1.0, on_tile: Callable[[int, int, TileStat], None] | None = None) -> StillResult:
    """Carica il payload nell'harness `h` e renderizza l'immagine a tempo `t`, tile per tile.

    `on_tile(i, n, stat)` dopo ogni tile (avanzamento). Il bloom del player non si applica: lavora
    sull'immagine intera, non su un tile."""
    validate_still_args(width, height, spp, tile, quality)
    res = h.load(payload)
    if not res["ok"]:
        raise CompileFailed(list(res["errors"]))
    info = h.info()
    tile = min(tile, int(info.get("maxTextureSize") or tile))
    warnings: list[str] = []
    if (payload.get("post") or {}).get("bloom"):
        warnings.append("bloom is not applied to stills yet (it works on the whole frame, not on tiles)")
    duration = float(payload["meta"]["duration_s"])
    t = min(max(0.0, t), duration)

    img = np.zeros((height, width, 3), dtype=np.uint8)
    rects = [(x, y, min(tile, width - x), min(tile, height - y))
             for y in range(0, height, tile) for x in range(0, width, tile)]
    stats: list[TileStat] = []
    t0 = time.perf_counter()
    for i, (x, y, w, hh) in enumerate(rects):
        # GL ha l'origine in basso a sinistra: il tile in alto nell'immagine ha la y GL più grande
        r = h.still_tile({"t": t, "width": width, "height": height, "x": x, "y": height - y - hh,
                          "w": w, "h": hh, "spp": spp, "quality": quality})
        px = np.frombuffer(base64.b64decode(r["data"]), dtype=np.uint8).reshape(hh, w, 3)
        img[y:y + hh, x:x + w] = px[::-1]
        st = TileStat(x=x, y=y, w=w, h=hh, ms_total=float(r["msTotal"]), ms_max=float(r["msMax"]))
        stats.append(st)
        if on_tile is not None:
            on_tile(i, len(rects), st)
    wall_ms = (time.perf_counter() - t0) * 1000
    slowest = max((s.ms_max for s in stats), default=0.0)
    if slowest > WATCHDOG_WARN_MS:
        warnings.append(f"slowest sample took {slowest:.0f} ms: close to the GPU watchdog (~2 s on Windows), "
                        "use a smaller tile")
    return StillResult(image=img, renderer=str(info["renderer"]), t=t, spp=spp, quality=quality, tile=tile,
                       wall_ms=wall_ms, tiles=stats, warnings=warnings)
