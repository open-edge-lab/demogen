// Parità semantica con demogen/spec/timeline.py: i casi attesi arrivano dai
// vettori condivisi generati da Python (shared/vectors/timeline_cases.json).

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { stateAt, Timeline } from "../src/timeline";

const here = dirname(fileURLToPath(import.meta.url));
const cases = JSON.parse(
  readFileSync(join(here, "../../shared/vectors/timeline_cases.json"), "utf-8"),
) as { timeline: Timeline; cases: { t: number; expect: Record<string, unknown> }[] }[];

describe("stateAt vs vettori condivisi (pytest genera gli stessi valori)", () => {
  for (const { timeline, cases: cs } of cases) {
    it(`timeline bpm=${timeline.bpm} scene=${timeline.scenes.length}`, () => {
      for (const c of cs) {
        const got = stateAt(timeline, c.t) as unknown as Record<string, unknown>;
        for (const [k, v] of Object.entries(c.expect)) {
          if (typeof v === "number") {
            expect(got[k], `t=${c.t} campo ${k}`).toBeCloseTo(v, 6);
          } else {
            expect(got[k], `t=${c.t} campo ${k}`).toBe(v);
          }
        }
      }
    });
  }
});
