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

  private player: Player | null = null;

  async connectedCallback(): Promise<void> {
    const src = this.getAttribute("src");
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.display = "block";
    this.appendChild(canvas);
    let payload: unknown;
    if (src) {
      const res = await fetch(src);
      payload = await res.json();
    } else {
      const inline = this.querySelector('script[type="application/json"]');
      payload = inline ? JSON.parse(inline.textContent ?? "null") : null;
    }
    this.player = new Player(canvas, parsePayload(payload), {
      autoPlay: this.getAttribute("autoplay") !== "none",
    });
    await this.player.load();
  }

  disconnectedCallback(): void {
    this.player?.dispose();
  }
}

if (typeof customElements !== "undefined" && !customElements.get("demogen-player")) {
  customElements.define("demogen-player", DemogenPlayerElement);
}
