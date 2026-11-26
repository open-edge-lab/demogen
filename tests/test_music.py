"""Colonna sonora (passo SM, orchestrator/music.py): gate dell'ascolto, errori di compilazione con le
righe del compositore, prompt, scelta della versione, robustezza degli onset e ciclo completo
compositore → ascolto → revisione nell'harness."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from demogen.config import Config
from demogen.critic.metrics_audio import audio_metrics
from demogen.llm.fake import FAKE_MUSIC, FakeLLM, FakeResponse, _fake_spec, fake_client_factory
from demogen.orchestrator import music
from demogen.orchestrator import prompts as P
from demogen.orchestrator.pipeline import Pipeline
from demogen.project.store import Project
from demogen.spec.models import DemoSpec

CFG = Config.model_validate({"providers": {}, "roles": {}})


def _spec() -> DemoSpec:
    return DemoSpec.model_validate(_fake_spec("neon plasma", 8.0, 120.0, "modern"))


def _m(**over) -> dict:
    """Metriche di una musica sana; `over` le peggiora una alla volta."""
    base = {"compiled": True, "rms": 0.2, "peak": 0.7, "clipped": False, "nan_ratio": 0.0,
            "realtime_factor": 50.0, "silent_bar_ratio": 0.0,
            "onset_vs_beat": {"n_onsets": 16, "n_strong": 16, "mean_abs_err_ms": 1.0, "max_abs_err_ms": 2.0}}
    return base | over


def _envelope(src: str, notes: str = "scripted") -> str:
    return '```json\n{"notes": "' + notes + '"}\n```\n\n```glsl\n' + src + "```\n"


# ---------------------------------------------------------------- gate (senza browser)
def test_music_gates_musica_sana_senza_issue() -> None:
    assert music.music_gates(_m(), CFG) == []


def test_music_gates_muta_bloccante() -> None:
    issues = music.music_gates(_m(rms=0.0, silent_bar_ratio=1.0), CFG)
    assert [i.severity for i in issues] == ["blocker"]  # muta: niente avviso "battute mute" in più
    assert "music silent or nearly silent" in issues[0].description
    assert f"minimum {CFG.audio.min_rms}" in issues[0].description
    assert "o.x and o.y" in issues[0].suggested_fix


def test_music_gates_nan_bloccante() -> None:
    issues = music.music_gates(_m(nan_ratio=0.0125), CFG)
    assert [i.severity for i in issues] == ["blocker"]
    assert issues[0].description == "NaN/Inf in the audio (0.0125 of the samples)"


def test_music_gates_troppo_pesante_bloccante() -> None:
    lim = CFG.audio.min_realtime_factor
    issues = music.music_gates(_m(realtime_factor=lim - 2.5), CFG)
    assert [i.severity for i in issues] == ["blocker"]
    assert issues[0].description == f"too heavy to compute: {lim - 2.5:.1f}x realtime (minimum {lim:g}x)"
    assert "44100 times per second" in issues[0].suggested_fix
    # al limite, o senza misura (calcolo non cronometrato), nessun problema
    assert music.music_gates(_m(realtime_factor=lim), CFG) == []
    assert music.music_gates(_m(realtime_factor=None), CFG) == []


def test_music_gates_battute_mute_major() -> None:
    issues = music.music_gates(_m(silent_bar_ratio=0.6), CFG)
    assert [i.severity for i in issues] == ["major"]
    assert issues[0].description == "more than half of the bars are silent (60%)"
    assert music.music_gates(_m(silent_bar_ratio=0.5), CFG) == []  # metà esatta: ancora accettabile


def test_music_gates_clip_e_onset_major_dai_gate() -> None:
    # clip e colpi fuori dal beat arrivano da run_gates (critic/gates.py): solo avvisi
    clipped = music.music_gates(_m(clipped=True, peak=1.0), CFG)
    assert [i.severity for i in clipped] == ["major"] and "0.999" in clipped[0].description
    err = CFG.audio.max_onset_err_ms + 7.5
    late = music.music_gates(_m(onset_vs_beat={"mean_abs_err_ms": err, "n_strong": 16}), CFG)
    assert [i.severity for i in late] == ["major"] and f"{err:.1f}" in late[0].description
    ok = music.music_gates(_m(onset_vs_beat={"mean_abs_err_ms": CFG.audio.max_onset_err_ms}), CFG)
    assert ok == []
    both = music.music_gates(_m(rms=0.0, clipped=True), CFG)
    assert [i.severity for i in both] == ["blocker", "major"]


# ---------------------------------------------------------------- errori, libreria, sezioni, prompt
def test_compile_errors_con_le_righe_del_compositore() -> None:
    errs = ["Error: shader compile error:\nERROR: 3:5: 'x' : undeclared identifier\n"
            "ERROR: 0:40: 'q' : header error\n--- sorgente ---\nvoid mainAudio(out vec4 o, in float t) {}"]
    assert music.compile_errors(errs) == ["line 5: 'x' : undeclared identifier"]
    # stesso risultato col marcatore inglese del player
    assert music.compile_errors([errs[0].replace("--- sorgente ---", "--- source ---")]) == [
        "line 5: 'x' : undeclared identifier"]
    # nessuna riga del compositore: il log grezzo, senza il sorgente accodato
    assert music.compile_errors(["link failed: too many uniforms\n--- source ---\nfloat x;"]) == [
        "link failed: too many uniforms"]


def test_library_reference_ha_le_firme() -> None:
    ref = music.library_reference()
    assert "`float chipKick(float t)`" in ref
    assert "`float chipBass(float t, float semi)`" in ref
    assert "`float hash11(float p)`: deterministic hash in [0,1)" in ref


def test_sezioni_della_timeline_in_battute_e_secondi() -> None:
    secs = music.sections(_spec())  # 4 battute a 120 bpm: 2 + 2
    assert [(s["id"], s["start_bar"], s["end_bar"], s["t0"], s["t1"]) for s in secs] == [
        ("s1", 0, 2, 0.0, 4.0), ("s2", 2, 4, 4.0, 8.0)]
    assert secs[1]["title"] == "Plasma variant" and secs[1]["transition"] == "crossfade"
    assert secs[0]["mood"] == "colorful plasma pulsing on the beat"


class _Ctx:
    def __init__(self) -> None:
        self.cfg = CFG


def test_prompt_del_compositore() -> None:
    spec = _spec()
    user = P.render("composer_music.md.j2", **music._common_vars(_Ctx(), spec, "  acid techno with a 303 line "))
    assert "Music requested by the user" in user and "acid techno with a 303 line\n" in user
    assert 's2 "Plasma variant": bars 2–4 (4.0–8.0 s), enters with "crossfade"' in user
    assert "void mainAudio(out vec4 o, in float t)" in user  # il contratto
    assert "`float chipKick(float t)`" in user  # la libreria
    assert f"under {CFG.audio.max_onset_err_ms} ms" in user
    assert f"at least {CFG.audio.min_realtime_factor}x faster than realtime" in user
    assert "neon plasma" in user  # il prompt della demo
    # senza prompt musicale: niente sezione dell'utente
    assert "Music requested by the user" not in P.render("composer_music.md.j2",
                                                         **music._common_vars(_Ctx(), spec, ""))


def test_prompt_di_revisione() -> None:
    spec = _spec()
    user = P.render("composer_revise.md.j2", **music._common_vars(_Ctx(), spec, ""), current_src="void x;",
                    issues_text="[blocker] the music does not compile: line 2: boom",
                    metrics_text=music._metrics_text({"compiled": False}))
    assert "line 2: boom" in user and "did not compile" in user and "void x;" in user
    assert "Sections: s1 bars 0–2; s2 bars 2–4" in user


# ---------------------------------------------------------------- scelta della versione
def _ver(adir: Path, v: int, severities: list[str] | None) -> None:
    (adir / f"v{v}.glsl").write_text("x", encoding="utf-8")
    if severities is not None:
        issues = [{"severity": s, "description": s} for s in severities]
        (adir / f"v{v}.issues.json").write_text(json.dumps(issues), encoding="utf-8")


def test_select_music_ultima_senza_blocker(tmp_path: Path) -> None:
    assert music.select_music(tmp_path) is None  # nessuna versione
    _ver(tmp_path, 1, ["blocker"])
    assert music.select_music(tmp_path) is None  # solo bloccanti: demo muta
    _ver(tmp_path, 2, ["major", "minor"])
    _ver(tmp_path, 3, ["blocker", "major"])
    _ver(tmp_path, 4, None)  # ascolto mai completato: non conta
    assert music.select_music(tmp_path) == "v2"
    _ver(tmp_path, 10, [])
    assert music.select_music(tmp_path) == "v10"  # ordine numerico, non alfabetico


# ---------------------------------------------------------------- onset su audio sintetico
SR, BPM, DUR = 44100, 120.0, 8.0


def _kick(tl: np.ndarray) -> np.ndarray:
    """chipKick di audio/chip.glsl in numpy."""
    k, f0, fi = 30.0, 150.0, 45.0
    ph = 2 * np.pi * (fi * tl + (f0 - fi) / k * (1.0 - np.exp(-k * tl)))
    return np.sin(ph) * np.exp(-tl * 8.0) + np.exp(-tl * 90.0) * 0.5 * np.sin(2 * np.pi * 1000.0 * tl)


def _kick_and_bass(shift_s: float) -> np.ndarray:
    t = np.arange(int(SR * DUR)) / SR
    beat = 60.0 / BPM
    kicks = np.where(t >= shift_s, _kick(np.mod(t - shift_s, beat)), 0.0)
    bass = np.sign(np.sin(2 * np.pi * 55.0 * t)) * 0.21  # square sostenuto a 55 Hz, come chipBass
    return np.tanh((kicks + bass) * 0.9)


def test_onset_sul_beat_con_basso_sostenuto() -> None:
    # il basso sostenuto non deve generare colpi "forti" spuri fuori dal beat
    obe = audio_metrics(_kick_and_bass(0.0), SR, BPM)["onset_vs_beat"]
    assert obe["mean_abs_err_ms"] < 5.0, obe
    assert obe["n_strong"] >= 12, obe  # i kick (16) vengono trovati quasi tutti


def test_onset_fuori_dal_beat_di_60ms() -> None:
    obe = audio_metrics(_kick_and_bass(0.060), SR, BPM)["onset_vs_beat"]
    assert obe["mean_abs_err_ms"] > 5.0, obe


def _pluck_arpeggio(note_s: float, offset_s: float = 0.0) -> np.ndarray:
    """Arpeggio di onde quadre pizzicate, una nota ogni `note_s`, senza cassa (come una chiptune leggera)."""
    t = np.arange(int(SR * DUR)) / SR
    tl = np.mod(t - offset_s, note_s)
    idx = np.floor((t - offset_s) / note_s).astype(int) % 4
    freq = np.array([220.0, 261.6, 329.6, 440.0])[idx]
    return np.where(t >= offset_s, 0.3 * np.sign(np.sin(2 * np.pi * freq * tl)) * np.exp(-tl * 12.0), 0.0)


def test_arpeggio_in_ottavi_senza_cassa_e_a_tempo() -> None:
    # run reale: chiptune a 128 BPM in ottavi, errore 107 ms contro i soli beat ma a tempo entro 2 ms
    obe = audio_metrics(_pluck_arpeggio(60.0 / BPM / 2), SR, BPM)["onset_vs_beat"]
    assert obe["mean_abs_err_ms"] < 5.0, obe


def test_musica_a_un_altro_tempo_resta_fuori_griglia() -> None:
    # sedicesimi a 137 BPM analizzati come se fossero a 120: slegata dal BPM della demo
    obe = audio_metrics(_pluck_arpeggio(60.0 / 137.0 / 4), SR, BPM)["onset_vs_beat"]
    assert obe["mean_abs_err_ms"] > 5.0, obe


# ---------------------------------------------------------------- ciclo nell'harness
class _Composer(FakeLLM):
    """Compositore con risposte forzate (in ordine), poi quelle del fake; registra i prompt."""

    def __init__(self, config=None, role: str = "orchestrator", *, answers: list[str] | None = None, **kw) -> None:
        super().__init__(config, role, **kw)
        self.answers = list(answers or [])
        self.prompts: list[tuple[str, str]] = []

    def chat(self, messages, *, step: str = "", **kw) -> FakeResponse:
        self.prompts.append((step, messages[-1]["content"]))
        if self.answers:
            self.calls.append(step)
            return FakeResponse(content=self.answers.pop(0))
        return super().chat(messages, step=step, **kw)


def _pipe(tmp_path: Path, answers: list[str] | None = None) -> Pipeline:
    if answers is None:
        return Pipeline(Project(tmp_path / "p"), CFG, client_factory=fake_client_factory)

    def factory(config=None, role: str = "orchestrator", **kw):
        return _Composer(config, role, answers=answers, **kw)

    return Pipeline(Project(tmp_path / "p"), CFG, client_factory=factory)


def _issues(adir: Path, v: int) -> list[dict]:
    return json.loads((adir / f"v{v}.issues.json").read_text(encoding="utf-8"))


def test_run_music_compositore_finto(harness, tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    assert music.run_music(pipe, harness, _spec(), "") == "v1"
    adir = pipe.project.path / "audio"
    for name in ("v1.glsl", "v1.meta.json", "v1.metrics.json", "v1.issues.json", "v1.spectrogram.png"):
        assert (adir / name).exists(), name
    assert json.loads((adir / "best.json").read_text(encoding="utf-8")) == {"version": "v1"}
    assert not any(i["severity"] == "blocker" for i in _issues(adir, 1))
    m = json.loads((adir / "v1.metrics.json").read_text(encoding="utf-8"))
    assert m["compiled"] and m["rms"] > CFG.audio.min_rms and m["nan_ratio"] == 0.0
    assert m["realtime_factor"] is not None and m["analyzed_s"] == pytest.approx(8.0)
    assert pipe.client("composer").calls == ["music"]
    assert music.best_music_src(pipe).strip() == FAKE_MUSIC.strip()


BROKEN = "void mainAudio(out vec4 o, in float t) {\n    float s = sin(6.2831853 * 220.0 * t) * 0.5\n" \
         "    o = vec4(s, s, 0.0, 1.0);\n}\n"  # manca il ';' alla riga 2


def test_run_music_errore_di_sintassi_poi_revisione(harness, tmp_path: Path) -> None:
    pipe = _pipe(tmp_path, [_envelope(BROKEN), _envelope(FAKE_MUSIC, "fixed")])
    assert music.run_music(pipe, harness, _spec(), "dark synthwave") == "v2"
    adir = pipe.project.path / "audio"
    m1 = json.loads((adir / "v1.metrics.json").read_text(encoding="utf-8"))
    assert m1["compiled"] is False and m1["errors"]
    err = m1["errors"][0]
    assert err.startswith(("line 2:", "line 3:")), err  # righe del codice del compositore, non dell'assemblato
    (blk,) = [i for i in _issues(adir, 1) if i["severity"] == "blocker"]
    assert blk["description"].startswith("the music does not compile: line ")
    assert not (adir / "v1.spectrogram.png").exists()

    composer = pipe.client("composer")
    assert [s for s, _ in composer.prompts] == ["music", "music_revise"]
    revise = composer.prompts[1][1]
    assert err in revise and "did not compile" in revise and BROKEN.strip() in revise
    assert "dark synthwave" in revise  # il prompt musicale resta la priorità
    assert json.loads((adir / "v2.meta.json").read_text(encoding="utf-8"))["parent"] == 1
    assert not any(i["severity"] == "blocker" for i in _issues(adir, 2))
    assert json.loads((adir / "best.json").read_text(encoding="utf-8")) == {"version": "v2"}


def test_run_music_risposta_senza_codice_poi_revisione(harness, tmp_path: Path) -> None:
    pipe = _pipe(tmp_path, ["here is my song, no code", _envelope(FAKE_MUSIC)])
    assert music.run_music(pipe, harness, _spec()) == "v2"
    adir = pipe.project.path / "audio"
    (blk,) = _issues(adir, 1)
    assert blk["severity"] == "blocker" and blk["description"].startswith("response without a valid ```glsl block")
    assert (adir / "v1.glsl").read_text(encoding="utf-8") == ""


SILENT = "void mainAudio(out vec4 o, in float t) {\n    o = vec4(0.0);\n}\n"


def test_run_music_muta_bloccante(harness, tmp_path: Path, capsys) -> None:
    n = CFG.budget.max_iterations_per_scene
    pipe = _pipe(tmp_path, [_envelope(SILENT)] * n)
    assert music.run_music(pipe, harness, _spec()) is None
    adir = pipe.project.path / "audio"
    for v in range(1, n + 1):
        blk = [i for i in _issues(adir, v) if i["severity"] == "blocker"]
        assert blk and blk[0]["description"].startswith("music silent or nearly silent"), blk
    assert json.loads((adir / "best.json").read_text(encoding="utf-8")) == {"version": None}
    assert music.best_music_src(pipe) == ""
    out = capsys.readouterr().out
    assert "[music] v1: music silent" in out and "[music] no usable version: the demo will be silent" in out


def test_run_music_versione_vuota_non_fa_da_genitore(harness, tmp_path: Path) -> None:
    pipe = _pipe(tmp_path, [_envelope(SILENT), "no code this time", _envelope(FAKE_MUSIC)])
    assert music.run_music(pipe, harness, _spec()) == "v3"
    adir = pipe.project.path / "audio"
    assert (adir / "v2.glsl").read_text(encoding="utf-8") == ""
    # la v3 rivede la v1 (l'ultimo codice vero), non la v2 vuota
    assert json.loads((adir / "v3.meta.json").read_text(encoding="utf-8"))["parent"] == 1
