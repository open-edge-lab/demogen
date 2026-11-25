// Semantica della timeline: identica a demogen/spec/timeline.py (verificata dai
// vettori condivisi in shared/vectors/timeline_cases.json).

export type Transition = "cut" | "crossfade" | "flash" | "fade_black";

export interface SceneSlot {
  id: string;
  start_bar: number;
  bars: number;
  transition_in: Transition;
  transition_bars: number;
}

export interface Timeline {
  bpm: number;
  beats_per_bar: number;
  scenes: SceneSlot[];
}

export interface TimelineState {
  sceneId: string; // scena attiva
  prevSceneId: string | null; // durante una transizione: scena che esce
  nextSceneId: string | null; // durante una transizione: scena che entra
  transition: Transition; // "cut" se nessuna transizione in corso
  alpha: number; // 0..1 progresso della transizione
  beat: number;
  bar: number;
  sceneTime: number; // secondi dall'inizio della scena attiva
  sceneProgress: number; // 0..1 nella scena attiva
  /** Durante una transizione: tempo della scena ENTRANTE (negativo prima del suo start_bar). */
  nextSceneTime: number | null;
  durationS: number; // durata totale della timeline
}

export function stateAt(tl: Timeline, t: number): TimelineState {
  const secPerBeat = 60 / tl.bpm;
  const beat = t / secPerBeat;
  const bar = beat / tl.beats_per_bar;
  const scenes = tl.scenes;
  const last = scenes[scenes.length - 1];
  const durationS = last.start_bar * tl.beats_per_bar * secPerBeat + last.bars * tl.beats_per_bar * secPerBeat;

  // scena attiva: ultima con start_bar <= bar (clamp ai bordi)
  let idx = 0;
  for (let i = 0; i < scenes.length; i++) {
    if (bar >= scenes[i].start_bar) idx = i;
  }
  const cur = scenes[idx];

  // transizione in ingresso della scena successiva durante le sue transition_bars finali
  let transition: Transition = "cut";
  let alpha = 1;
  let prevSceneId: string | null = null;
  let nextSceneId: string | null = null;
  let nextSceneTime: number | null = null;
  if (idx + 1 < scenes.length) {
    const nxt = scenes[idx + 1];
    const t0 = nxt.start_bar - nxt.transition_bars;
    if (nxt.transition_in !== "cut" && nxt.transition_bars > 0 && bar >= t0 && bar < nxt.start_bar) {
      transition = nxt.transition_in;
      alpha = (bar - t0) / nxt.transition_bars;
      prevSceneId = cur.id;
      nextSceneId = nxt.id;
      nextSceneTime = t - nxt.start_bar * tl.beats_per_bar * secPerBeat;
    }
  }

  const sceneStartS = cur.start_bar * tl.beats_per_bar * secPerBeat;
  const sceneDurS = cur.bars * tl.beats_per_bar * secPerBeat;
  return {
    sceneId: cur.id,
    prevSceneId,
    nextSceneId,
    transition,
    alpha: Math.min(1, Math.max(0, alpha)),
    beat,
    bar,
    sceneTime: t - sceneStartS,
    sceneProgress: sceneDurS > 0 ? Math.min(1, Math.max(0, (t - sceneStartS) / sceneDurS)) : 0,
    nextSceneTime,
    durationS,
  };
}
