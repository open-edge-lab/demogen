"""LLM finto deterministico per E2E senza API reali (`demogen generate --fake`).

Risponde in base allo `step` passato a chat(): produce uno spec valido, uno
style valido, scene valide che usano la libreria, e una critica "accept".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .. import progress


@dataclass
class FakeResponse:
    content: str
    model: str = "fake-llm"
    usage: dict = None  # type: ignore[assignment]
    cost_usd: float = 0.0
    latency_s: float = 0.01
    raw: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.usage is None:
            self.usage = {"prompt_tokens": 100, "completion_tokens": 200}
        if self.raw is None:
            self.raw = {}


FAKE_STYLE = """const vec3 PALETTE[16] = vec3[16](
    vec3(0.02,0.02,0.05), vec3(0.10,0.08,0.25), vec3(0.45,0.15,0.65), vec3(0.95,0.30,0.65),
    vec3(1.00,0.55,0.45), vec3(1.00,0.75,0.30), vec3(0.55,0.95,0.45), vec3(0.20,0.85,0.55),
    vec3(0.10,0.75,0.85), vec3(0.15,0.45,0.95), vec3(0.45,0.35,1.00), vec3(0.95,0.95,1.00),
    vec3(0.05,0.05,0.12), vec3(0.20,0.10,0.40), vec3(0.75,0.20,0.75), vec3(1.00,0.90,0.45)
);
const int PALETTE_N = 16;
vec3 finalize(vec3 col, vec2 uv) {
#ifdef PROFILE_RETRO
    return retroFinalize(col, uv, gl_FragCoord.xy, PALETTE, PALETTE_N);
#else
    col = aces(col);
    col = vignette(col, uv, 0.3);
    return toSRGB(col);
#endif
}
"""

FAKE_SCENE = """void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = (fragCoord - 0.5 * iResolution.xy) / iResolution.y;
    // funzione generata dall'oracolo matematico (math_request verificato)
    float e = ease_smooth(clamp(iTime * 0.1, 0.0, 1.0));
    float v = sin(uv.x * 4.0 + iTime) + sin(uv.y * 4.0 - iTime * 1.3)
            + sin((uv.x + uv.y) * 3.0 + uBeatPhase * 6.2831);
    vec3 col = cosPalette(0.5 + 0.15 * v + uBar * 0.05 + e * 0.05,
                          vec3(0.5), vec3(0.5), vec3(1.0), vec3(0.0, 0.33, 0.67));
    col *= 0.6 + 0.4 * beatPulse(uBeatPhase, 6.0);
    fragColor = vec4(finalize(col, uv), 1.0);
}
"""

# colonna sonora del fake: chiptune sul beat (kick, hat in levare, basso), come l'esempio audio_chip
FAKE_MUSIC = """void mainAudio(out vec4 o, in float t) {
    float beatDur = 60.0 / BPM;
    float beat = floor(t / beatDur);
    float ph = fract(t / beatDur);
    float s = chipKick(ph * beatDur);
    float off = fract(ph * 2.0);
    s += chipHat(off * beatDur * 0.5) * step(0.5, off);
    s += chipBass(t, mod(beat, 8.0) < 4.0 ? 0.0 : 7.0) * 0.7;
    s = tanh(s * 0.9);
    o = vec4(s, s * 0.95, 0.0, 1.0);
}
"""

# math_requests del fake: uno verificato (easing), uno volutamente falso (sdf senza regione negativa)
FAKE_MATH_REQUESTS = [
    {
        "id": "ease_smooth",
        "kind": "easing",
        "description": "smoothstep-like easing f(0)=0 f(1)=1",
        "inputs": {"t": "float"},
        "output_signature": "float ease_smooth(float t)",
        "expr": "t * t * (3.0 - 2.0 * t)",
        "claim": {"domain": [[0.0, 1.0]], "tol": 1e-9},
    },
    {
        "id": "sdf_falso",
        "kind": "sdf",
        "description": "false claim: len2 has no negative region",
        "inputs": {"x": "float", "y": "float"},
        "output_signature": "float sdf_falso(float x, float y)",
        "expr": "len2(x, y)",
        "claim": {"domain": [[-2.0, 2.0], [-2.0, 2.0]], "samples": 32},
    },
]


def _fake_spec(prompt: str, duration_s: float, bpm: float, profile: str) -> dict:
    total_bars = max(2, round(duration_s * bpm / 60 / 4))
    half = total_bars // 2
    scenes = [
        {"id": "s1", "start_bar": 0, "bars": half, "transition_in": "cut", "transition_bars": 0},
        {
            "id": "s2",
            "start_bar": half,
            "bars": total_bars - half,
            "transition_in": "crossfade",
            "transition_bars": 1,
        },
    ]
    return {
        "title": "Fake Demo",
        "prompt": prompt,
        "duration_s": total_bars * 4 * 60 / bpm,
        "loop": False,
        "profile": profile,
        "timeline": {"bpm": bpm, "beats_per_bar": 4, "scenes": scenes},
        "scenes": [
            {
                "id": "s1",
                "title": "Plasma",
                "description": "colorful plasma pulsing on the beat",
                "motion": "pulses with uBeatPhase",
                "techniques": ["cosPalette", "beatPulse"],
                "camera": "2D fullscreen",
                "perf_tier": "light",
            },
            {
                "id": "s2",
                "title": "Plasma variant",
                "description": "plasma with different palette phase",
                "motion": "rotating palette with uBar",
                "techniques": ["cosPalette"],
                "camera": "2D fullscreen",
                "perf_tier": "light",
            },
        ],
        "art_direction": "magenta/cyan neon, high contrast",
        "palette_hint": ["#ff00ff", "#00ffff"],
        "audio_brief": "not in this phase",
        "text": None,
        "avoid": ["checkered plane", "rainbow plasma"],
    }


class FakeLLM:
    """Sostituisce LLMClient nei test/smoke: stessa interfaccia (chat/achat)."""

    def __init__(self, config=None, role: str = "orchestrator", **kwargs: Any) -> None:
        self.role = role
        self.calls: list[str] = []

    def _respond(self, step: str, prompt_hint: str = "") -> FakeResponse:
        self.calls.append(step)
        if step == "brief":
            spec = _fake_spec(prompt_hint, 8.0, 120.0, "modern")
            return FakeResponse(content=json.dumps(spec))
        if step == "style":
            return FakeResponse(
                content='```json\n{"bloom": {"threshold": 0.8, "intensity": 0.4}}\n```\n\n'
                '```glsl\n' + FAKE_STYLE + "```\n"
            )
        if step.startswith("draft"):
            scene_id = step.split(":", 1)[1] if ":" in step else "s1"
            return FakeResponse(
                content='```json\n{"scene_id": "' + scene_id + '", "notes": "fake plasma", "perf_tier": "light", '
                '"math_requests": ' + json.dumps(FAKE_MATH_REQUESTS) + "}"
                "\n```\n\n```glsl\n" + FAKE_SCENE + "```\n"
            )
        if step.startswith("music"):
            return FakeResponse(
                content='```json\n{"notes": "fake chiptune: kick, offbeat hat, bass", "key": "A minor"}\n```\n\n'
                "```glsl\n" + FAKE_MUSIC + "```\n"
            )
        if step.startswith("fixer"):
            return FakeResponse(content="```glsl\n" + FAKE_SCENE + "```\n")
        if step.startswith("revise"):
            scene_id = step.split(":", 1)[1] if ":" in step else "s1"
            return FakeResponse(
                content='```json\n{"scene_id": "' + scene_id + '", "notes": "fake revise", '
                '"perf_tier": "light"}\n```\n\n```glsl\n' + FAKE_SCENE + "```\n"
            )
        if step.startswith("critique"):
            return FakeResponse(
                content=json.dumps(
                    {
                        "scores": {
                            "brief": 8, "composition": 7, "color": 8, "motion": 7,
                            "technical": 9, "originality": 6,
                        },
                        "issues": [],
                        "verdict": "accept",
                        "summary": "fake scene ok",
                    }
                )
            )
        return FakeResponse(content="OK")

    @staticmethod
    def _replan(messages) -> FakeResponse:
        """Il piano precedente (risposta dell'assistente) con la nota dell'utente nella prima scena."""
        prev = next(m["content"] for m in reversed(messages) if m.get("role") == "assistant")
        note = ""
        for m in messages:
            c = m.get("content")
            if isinstance(c, str) and "Change requested by the user:" in c:
                note = c.split("Change requested by the user:", 1)[1].splitlines()[0].strip()
        spec = json.loads(prev)
        spec["scenes"][0]["description"] = f"{spec['scenes'][0]['description']} ({note})"
        return FakeResponse(content=json.dumps(spec))

    def chat(self, messages, *, step: str = "", **kwargs: Any) -> FakeResponse:
        if step == "brief:replan":
            with progress.llm_call(self.role, "fake", step) as call:
                self.calls.append(step)
                call.update(cost=0.0, latency=0.0)
                return self._replan(messages)
        hint = ""
        for m in messages:
            c = m.get("content")
            if isinstance(c, str) and "User prompt:" in c:
                hint = c.split("User prompt:", 1)[1].splitlines()[0].strip()
        with progress.llm_call(self.role, "fake", step) as call:
            r = self._respond(step, hint)
            call.update(cost=0.0, latency=0.0)
            return r

    async def achat(self, messages, *, step: str = "", **kwargs: Any) -> FakeResponse:
        return self.chat(messages, step=step, **kwargs)


def fake_client_factory(config=None, role: str = "orchestrator", **kwargs: Any):
    return FakeLLM(config, role, **kwargs)
