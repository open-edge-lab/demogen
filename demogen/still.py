"""Immagini fisse ad alta risoluzione con il motore realtime.

L'immagine intera si divide in tile; per ogni tile il browser somma `spp` campioni sub-pixel in un
FBO float (player/src/still.ts) e Python ricompone il PNG. Un campione costa quanto un frame realtime
della stessa area, quindi nessun comando GPU dura abbastanza da far scattare il watchdog, qualunque
sia la dimensione finale o il numero di campioni. Il bloom del player lavora sul fotogramma intero:
qui si applica sull'immagine ricomposta (`apply_bloom`). Sull'immagine finale girano i gate di
qualità d'immagine della pipeline (NaN/Inf, nero).
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
BLOOM_REF_HEIGHT = 1080  # il bloom del player ha il raggio in pixel: lo still riproduce quello a questa altezza
# sigma del blur del player (5 letture lineari = gaussiana a 9 tap, pesi in post.ts) in texel a 1/4 di risoluzione
BLOOM_SIGMA_QUARTER = float(np.sqrt(2 * (0.3162162162 * 1.3846153846**2 + 0.0702702703 * 3.2307692308**2)))
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
    issues: list = field(default_factory=list)  # list[critic.models.Issue], gate sull'immagine finale
    bloom: bool = False

    @property
    def blockers(self) -> int:
        return sum(1 for i in self.issues if i.severity == "blocker")

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
            "bloom": self.bloom,
            "issues": [{"severity": i.severity, "description": i.description, "fix": i.suggested_fix}
                       for i in self.issues],
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


def _gauss1d(a: np.ndarray, sigma: float, axis: int) -> np.ndarray:
    """Sfocatura gaussiana lungo un asse, bordi replicati (somma di copie spostate: niente scipy)."""
    r = max(1, int(np.ceil(3.0 * sigma)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    p = np.pad(a, pad, mode="edge")
    n = a.shape[axis]
    out = np.zeros_like(a)
    for i, w in enumerate(k):
        out += w * np.take(p, np.arange(i, i + n), axis=axis)
    return out


def apply_bloom(img: np.ndarray, threshold: float, intensity: float, ref_height: int = BLOOM_REF_HEIGHT) -> np.ndarray:
    """Il bloom del player (player/src/post.ts) sull'immagine intera: bright pass a 1/4 di risoluzione,
    sfocatura gaussiana, somma saturata a 1. Il raggio cresce con l'altezza dell'immagine, così uno
    still 8K ha lo stesso alone del frame a `ref_height` invece di uno 4 volte più stretto."""
    h, w = img.shape[:2]
    h4, w4 = -(-h // 4), -(-w // 4)
    x = img.astype(np.float32) / 255.0
    pad = np.pad(x, ((0, h4 * 4 - h), (0, w4 * 4 - w), (0, 0)), mode="edge")
    q = pad.reshape(h4, 4, w4, 4, 3).mean(axis=(1, 3))
    luma = q @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    s = np.clip((luma - threshold) / 0.25, 0.0, 1.0)
    bright = q * (s * s * (3.0 - 2.0 * s))[..., None]
    sigma = BLOOM_SIGMA_QUARTER * h / ref_height
    blur = _gauss1d(_gauss1d(bright, sigma, 0), sigma, 1)
    from PIL import Image

    for c in range(3):  # un canale alla volta: un 8K float a 3 canali sono 400 MB
        up = np.asarray(Image.fromarray(blur[..., c]).resize((w4 * 4, h4 * 4), Image.BILINEAR))[:h, :w]
        x[..., c] = np.minimum(x[..., c] + up * intensity, 1.0)
    return (x * 255.0 + 0.5).astype(np.uint8)


def still_issues(nan_inf: dict, image: np.ndarray, cfg=None) -> list:
    """Gate di qualità d'immagine della pipeline sull'immagine finale: NaN/Inf (dal render float) e nero
    (luma Rec.709 < 0.02 come in critic/metrics_video, su un pixel ogni 4 per lato)."""
    from .critic.gates import run_gates

    f = image[::4, ::4].astype(np.float32) / 255.0
    luma = 0.2126 * f[..., 0] + 0.7152 * f[..., 1] + 0.0722 * f[..., 2]
    video = {"nan_ratio": float(nan_inf.get("nan_ratio", 0.0)), "inf_ratio": float(nan_inf.get("inf_ratio", 0.0)),
             "black_ratio": float((luma < 0.02).mean())}
    return run_gates({"video": video}, cfg)


def render_still(h, payload: dict, *, t: float, width: int, height: int, spp: int = 16, tile: int = 1024,
                 quality: float = 1.0, on_tile: Callable[[int, int, TileStat], None] | None = None,
                 cfg=None) -> StillResult:
    """Carica il payload nell'harness `h` e renderizza l'immagine a tempo `t`, tile per tile, poi il
    bloom (se il payload lo chiede) e i gate. `on_tile(i, n, stat)` dopo ogni tile (avanzamento)."""
    validate_still_args(width, height, spp, tile, quality)
    res = h.load(payload)
    if not res["ok"]:
        raise CompileFailed(list(res["errors"]))
    info = h.info()
    tile = min(tile, int(info.get("maxTextureSize") or tile))
    warnings: list[str] = []
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
    # NaN/Inf si vedono solo prima della quantizzazione: render float della scena a una risoluzione ridotta
    sw, sh = max(1, min(960, width)), max(1, min(540, height))
    nan_inf = h.scene_stats([t], sw, sh)[0]
    bloom = (payload.get("post") or {}).get("bloom")
    if bloom:
        img = apply_bloom(img, float(bloom["threshold"]), float(bloom["intensity"]))
    slowest = max((s.ms_max for s in stats), default=0.0)
    if slowest > WATCHDOG_WARN_MS:
        warnings.append(f"slowest sample took {slowest:.0f} ms: close to the GPU watchdog (~2 s on Windows), "
                        "use a smaller tile")
    return StillResult(image=img, renderer=str(info["renderer"]), t=t, spp=spp, quality=quality, tile=tile,
                       wall_ms=wall_ms, tiles=stats, warnings=warnings, issues=still_issues(nan_inf, img, cfg),
                       bloom=bool(bloom))
