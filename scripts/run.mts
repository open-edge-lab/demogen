// Lanciatore cross-platform di demogen (Windows, macOS, Linux): trova uv, crea l'ambiente Python se
// manca e avvia il menu interattivo (`demogen menu`, demogen/menu.py). Sostituisce run.ps1.
//
//   npm run menu                       menu interattivo (su Windows anche doppio click su run.cmd)
//   npm run menu -- --action list      elenco delle voci
//   npm run menu -- --action kill --yes
//   npm run menu -- --setup            uv sync prima del menu
//
// Node >= 22.18 esegue il TypeScript (.mts = modulo ES) direttamente (type stripping): niente build. Solo sintassi
// "cancellabile" (niente enum/namespace), controllata da `npm run typecheck:scripts`.

import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const WIN = process.platform === "win32";

export interface LaunchArgs {
  action: string;
  yes: boolean;
  setup: boolean;
  help: boolean;
}

/** Argomenti: --action <nome> | --action=<nome>, --yes, --setup, --help; accetta anche le forme di
 *  run.ps1 (-Action, -Yes, -Setup) per chi le ha nelle abitudini o in un collegamento. */
export function parseArgs(argv: string[]): LaunchArgs {
  const out: LaunchArgs = { action: "", yes: false, setup: false, help: false };
  for (let i = 0; i < argv.length; i++) {
    const raw = argv[i];
    const [flag, inline] = raw.includes("=") ? [raw.slice(0, raw.indexOf("=")), raw.slice(raw.indexOf("=") + 1)] : [raw, undefined];
    const key = flag.replace(/^-+/, "").toLowerCase();
    if (!flag.startsWith("-")) throw new Error(`unexpected argument: ${raw} (use --action <name>)`);
    if (key === "action" || key === "a") {
      const v = inline ?? argv[++i];
      if (v === undefined || v === "") throw new Error("--action needs a name or a number (--action list)");
      out.action = v;
    } else if (key === "yes" || key === "y") out.yes = true;
    else if (key === "setup") out.setup = true;
    else if (key === "help" || key === "h" || key === "?") out.help = true;
    else throw new Error(`unknown option: ${raw} (see --help)`);
  }
  return out;
}

/** Percorso di un eseguibile nel PATH (su Windows prova le estensioni di PATHEXT), o null. */
export function which(cmd: string, env: NodeJS.ProcessEnv = process.env): string | null {
  const exts = WIN ? (env.PATHEXT ?? ".EXE;.CMD;.BAT").split(";").filter(Boolean) : [""];
  for (const dir of (env.PATH ?? env.Path ?? "").split(delimiter)) {
    if (!dir) continue;
    for (const ext of exts) {
      const p = join(dir, WIN && !cmd.toLowerCase().endsWith(ext.toLowerCase()) ? cmd + ext : cmd);
      if (existsSync(p)) return p;
    }
  }
  return null;
}

/** Comando di uv: nel PATH, nell'installazione utente standard, oppure come modulo di Python. */
export function findUv(): string[] | null {
  const onPath = which("uv");
  if (onPath) return [onPath];
  for (const dir of [join(homedir(), ".local", "bin"), join(homedir(), ".cargo", "bin")]) {
    const p = join(dir, WIN ? "uv.exe" : "uv");
    if (existsSync(p)) return [p];
  }
  for (const py of WIN ? ["py", "python"] : ["python3", "python"]) {
    const p = which(py);
    if (p && spawnSync(p, ["-m", "uv", "--version"], { stdio: "ignore" }).status === 0) return [p, "-m", "uv"];
  }
  return null;
}

export function venvPython(repo: string = REPO): string {
  return WIN ? join(repo, ".venv", "Scripts", "python.exe") : join(repo, ".venv", "bin", "python");
}

/** Argomenti di uv per avviare il menu. */
export function menuArgs(a: LaunchArgs): string[] {
  const args = ["run", "--quiet", "demogen", "menu"];
  if (a.action) args.push("--action", a.action);
  if (a.yes) args.push("--yes");
  return args;
}

// colori: la stessa palette neon del menu, solo se la console li regge (NO_COLOR rispettato)
const tty = process.stdout.isTTY && !process.env.NO_COLOR;
const rgb = (hex: string) => (s: string): string => {
  if (!tty) return s;
  const n = parseInt(hex.slice(1), 16);
  return `\x1b[1;38;2;${n >> 16};${(n >> 8) & 255};${n & 255}m${s}\x1b[0m`;
};
const cyan = rgb("#05d9e8");
const red = rgb("#ff3355");
const dim = (s: string): string => (tty ? `\x1b[38;2;90;106;140m${s}\x1b[0m` : s);

const HELP = `demogen launcher: finds uv, sets up the Python environment if missing, starts the menu.

  npm run menu                          interactive menu (Windows: also double click run.cmd)
  npm run menu -- --action <name|n>     run one menu entry without the menu (--action list)
  npm run menu -- --action kill --yes   answer yes to confirmations
  npm run menu -- --setup               run uv sync first (Python dependencies updated)
`;

async function main(): Promise<number> {
  let args: LaunchArgs;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (e) {
    console.error(red(`error: ${(e as Error).message}`));
    return 2;
  }
  if (args.help) {
    process.stdout.write(HELP);
    return 0;
  }
  const uv = findUv();
  if (!uv) {
    console.error(red("uv not found: install it (https://docs.astral.sh/uv/) or run 'python -m pip install uv'"));
    return 1;
  }
  const [exe, ...pre] = uv;
  if (args.setup || !existsSync(venvPython())) {
    console.log(cyan("  setting up the Python environment (uv sync)…"));
    const r = spawnSync(exe, [...pre, "sync"], { cwd: REPO, stdio: "inherit" });
    if (r.status !== 0) {
      console.error(red(`  uv sync failed (exit code ${r.status ?? "?"}): the reason is above`));
      return r.status ?? 1;
    }
  }
  if (!args.action) console.log(dim("  starting the demogen menu…"));
  const child = spawn(exe, [...pre, ...menuArgs(args)], {
    cwd: REPO,
    stdio: "inherit",
    // riquadri e simboli del pannello (▰▱ ♪) in UTF-8 anche se la console ha un'altra code page
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
  });
  // Ctrl+C arriva anche al menu, che decide (interrompe il comando e torna al menu, o esce):
  // il lanciatore non deve morire prima e lasciare il menu orfano nella console
  const ignore = (): void => {};
  process.on("SIGINT", ignore);
  process.on("SIGBREAK", ignore);
  return await new Promise<number>((done) => {
    child.on("error", (e) => {
      console.error(red(`could not start uv: ${e.message}`));
      done(1);
    });
    child.on("exit", (code, signal) => done(code ?? (signal ? 130 : 1)));
  });
}

const invokedDirectly = process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedDirectly) {
  main().then((code) => process.exit(code));
}
