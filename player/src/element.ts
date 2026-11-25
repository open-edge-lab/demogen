// Custom element <demogen-player src="...demo"> per l'embed (usato anche
// dall'HTML standalone del bundle).

import { Player } from "./player";
import { parsePayload } from "./format";

// Base-safe: in ambienti senza DOM (node/SSR) l'import non deve crashare.
const ElementBase: typeof HTMLElement =
  typeof HTMLElement === "undefined" ? (class {} as unknown as typeof HTMLElement) : HTMLElement;

export class DemogenPlayerElement extends ElementBase {
  static get observedAttributes(): string[] {
    return ["src", "autoplay", "loop"];
  }

  player: Player | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private abort: AbortController | null = null;

  connectedCallback(): void {
    // idempotente: spostare l'elemento nel DOM non deve creare un secondo canvas/player
    if (this.player || this.abort) return;
    const abort = new AbortController();
    this.abort = abort;
    void this.boot(abort.signal).catch((e) => this.fail(e, abort.signal));
  }

  private async boot(signal: AbortSignal): Promise<void> {
    const src = this.getAttribute("src");
    let payload: unknown;
    if (src) {
      const res = await fetch(src, { signal });
      if (!res.ok) throw new Error(`fetch ${src}: HTTP ${res.status}`);
      payload = await res.json();
    } else {
      // Il parser upgrada l'elemento quando trova il tag di apertura, prima che i
      // figli (lo <script type="application/json">) siano nel DOM: se il documento
      // è ancora in parsing, aspetta DOMContentLoaded prima di leggerlo.
      if (document.readyState === "loading") {
        await new Promise<void>((resolve) =>
          window.addEventListener("DOMContentLoaded", () => resolve(), { once: true })
        );
      }
      const inline = this.querySelector('script[type="application/json"]');
      payload = inline ? JSON.parse(inline.textContent ?? "null") : null;
    }
    if (signal.aborted) return; // disconnesso durante il fetch: niente player orfano
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.display = "block";
    this.appendChild(canvas);
    this.canvas = canvas;
    const player = new Player(canvas, parsePayload(payload), {
      autoPlay: this.getAttribute("autoplay") !== "none",
    });
    this.player = player;
    await player.load();
    if (signal.aborted) player.dispose();
    else this.dispatchEvent(new CustomEvent("demogen-ready"));
  }

  private fail(e: unknown, signal: AbortSignal): void {
    if (signal.aborted) return;
    const msg = e instanceof Error ? e.message : String(e);
    this.setAttribute("data-error", msg);
    this.dispatchEvent(new CustomEvent("demogen-error", { detail: e }));
    console.error("demogen-player:", msg);
  }

  disconnectedCallback(): void {
    this.abort?.abort();
    this.abort = null;
    this.player?.dispose();
    this.player = null;
    this.canvas?.remove();
    this.canvas = null;
  }
}

if (typeof customElements !== "undefined" && !customElements.get("demogen-player")) {
  customElements.define("demogen-player", DemogenPlayerElement);
}
