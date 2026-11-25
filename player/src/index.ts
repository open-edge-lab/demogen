// API pubblica del player demogen.

export { Player } from "./player";
export type { PlayerOptions } from "./player";
export { parsePayload, textToUniform, textByteLength } from "./format";
export { PlaybackClock } from "./clock";
export type { DemoPayload } from "./format";
export { stateAt } from "./timeline";
export type { Timeline, SceneSlot, TimelineState, Transition } from "./timeline";
export { QualityController } from "./quality";
export { rendererInfo, isSoftwareRenderer } from "./gl";
export type { DemogenInfo } from "./gl";
export { buildHeader, buildFragment } from "./programs";

export {
  AudioEngine, buildAudioHeader, buildAudioFragment, planChunkStarts, chunkSchedule, AUDIO_BLOCK_SAMPLES,
} from "./audio";
export { DemogenPlayerElement } from "./element";
