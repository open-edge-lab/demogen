# Review del progetto e piano di correzione: lavoro rimanente

Documento per riprendere il lavoro nato dalla review completa del progetto (Python, player TS, libreria GLSL, test,
CI, docs). Contiene lo stato, i problemi ancora aperti e i batch di correzione da eseguire.

## Stato al 2026-11-25

| Batch | Contenuto | Stato |
|-------|-----------|-------|
| A | Config / `api_key` (il WIP non committato) | ✅ fatto: commit `377ca05` sul branch `fix/review-batch-a`, suite 88/88 |
| B | Integrità di test e CI | ✅ fatto: fixture `harness` (skip solo sull'avvio, fail con `CI=true`), golden obbligatori, sessione browser robusta; xfail strict per #21, #23, #32 |
| C | Sicurezza (bundle HTML, path, sandbox dell'oracolo) | ✅ fatto: escape di titolo e payload, slug per i file, path e id confinati, runner `-I -c`, clamp dei claim |
| D | Correttezza della pipeline LLM | da fare |
| E | Gate del critic (flash, perf, flicker) | da fare |
| F | Player TS | da fare |
| G | Oracolo matematico | da fare |
| H | Docs | da fare |

Ordine consigliato: B → C → D → E → F → G → H. Un commit per batch (`fix(<area>): …`); rivedere con l'utente alla
fine di ogni batch.

### Come riprendere

- **Branch:** `git checkout fix/review-batch-a`. `main` è fermo a `1520fcb`; il merge non è ancora stato fatto.
- **Ambiente:** `uv` è installato per l'utente via pip ma **non è nel PATH**, quindi va lanciato come
  `py -m uv …`. Per esempio:
  - `py -m uv run pytest -q`
  - `py -m uv run ruff check .`
  - `npm run build`
  - `npm run typecheck --workspace player`
  - `npm test --workspace player`

  `.venv` e Chromium per Playwright sono già installati.
- **Fine riga:** i file del repo sono **CRLF**. Non usare `sed -i` (in Git Bash converte tutto in LF): per le
  modifiche usare l'editor o Python con `read_text`/`write_text`.
- **Disciplina TDD:** per ogni correzione, prima un test che fallisce, poi la fix. A fine batch suite completa più
  ruff. La suite completa dura circa 1 minuto; quella di baseline senza cache del browser circa 5.
- **Ledger:** il ledger di esecuzione è in `.superpowers/sdd/…/progress.md`, ma è git-ignored e locale. Questo
  documento è il riferimento duraturo.

### Già risolto nel Batch A (non rifare)

- `resolve_role` con `inherit`:
  - eredita senza essere sovrascritto dai default (`exclude_unset`);
  - rileva i cicli;
  - i ruoli senza provider/model, o con provider inesistente, vengono rifiutati al load.
- `api_key` è `SecretStr`:
  - non compare in repr né nei traceback;
  - il placeholder `<…>` o una stringa vuota contano come chiave assente, quindi si ricade su `api_key_env`;
  - se manca la chiave OpenRouter, errore esplicito in `LLMClient`;
  - `models check` non si blocca su un ruolo rotto.
- `ensure_config`:
  - la chiave è scritta con escape YAML, mai in un commento;
  - avviso se il file non si chiama `demogen.yaml`, l'unico nome in `.gitignore` (stesso avviso in `demogen init`).
- Template: uno solo, `demogen/demo.yaml` (con la sezione `audio`). Eliminati `example.yaml` in root,
  `demogen/example.yaml` e `demogen.demo.yaml`. CLAUDE.md e i due piani in `docs/` sono già aggiornati sulla config.

---

## Problemi ancora aperti

I punti con ✔ sono stati verificati direttamente nel codice; gli altri vengono dalla lettura completa dei file da
parte della review.

### Sicurezza
1. ✔ **Iniezione HTML nel bundle** (`demogen/bundle/build.py:122,129`). `<title>` e `PAYLOAD` non hanno escape, e
   `json.dumps` non neutralizza `</script>` né `<!--`. Un testo scroller o un titolo generati dall'LLM possono
   eseguire script nel `.html`.
2. **Titolo LLM usato come nome file.** Il titolo passa da `steps.py:390` a `build.py:115,137`: con `/`, `..` o `:`
   (alternate data stream su NTFS) si scrive fuori da `out/` o in file invisibili. `slugify()` esiste ma non viene
   usato. In `project/store.py:44-46` manca il controllo che il path resti nel progetto.
3. ✔ **Runner dell'oracolo senza `-I`** (`math/safe_parse.py:159-168`): un `json.py` lasciato nella cartella temp
   viene importato. I parametri `samples`, `tol` e `tol_grad` li decide l'LLM (`verify.py:54-55,96`), e
   `samples=1e8` manda in OOM il processo padre.
4. **Network block di Playwright** fatto con `startswith(base_url)`, senza `/` finale (`browser/session.py:58-62`).

### Gate di sicurezza e prestazioni
5. ✔ **Il gate flash va in aliasing.** Campiona a 8–10 fps (`steps.py:256`, `cli.py:365`) e copre solo i primi 6 s,
   quindi uno strobo a 8 Hz risulta 0 flash.
6. ✔ **Il calcolo del flash non segue WCAG:**
   - `MIN_CELLS=16` (`flash.py:17`) corrisponde al 25% dello schermo, contro il 25% di 10° di WCAG (circa 2,8%).
   - La media per cella è fatta in sRGB prima della linearizzazione (`player/src/harness.ts:85-96`).
   - Ogni transizione viene contata come un flash, invece della coppia di transizioni opposte.
   - La regola del rosso scatta su una sola transizione.
   - Un flash a 2 Hz sul beat, conforme a WCAG, viene bloccato.
7. ✔ **I blocker non bloccano.** `pipeline.py:140` esce dal loop su `accept` o all'ultima iterazione ignorando i
   blocker. S9 (`pipeline.py:174-188`) stampa soltanto il conteggio e non analizza il flash sulla demo intera,
   transizioni comprese. Il flash di transizione in `compositor.ts:39` ignora `uFlashLimit`, che `player.ts:192`
   fissa a 1.
8. ✔ **Il gate perf ignora la risoluzione** (`critic/gates.py:36-49`): il p95 misurato a 480×270 viene confrontato
   col budget pensato per 1080p, e su SwiftShader col budget della GPU (il default di `generate` è `--gpu swiftshader`).
9. **Gate morti o inefficaci:**
   - flicker: z>4 con n≤16 campioni è matematicamente impossibile (`metrics_video.py:53-55`);
   - il gate floor non riceve mai `floor_samples`;
   - `loop_seam` misura i frame sbagliati;
   - le soglie sono hard-coded e `calibrate.json` non viene letto da nessuno.
10. **Burst e diff passati al critic non sono frame consecutivi** (`steps.py:290`), e `preview.bursts` non è usato.
11. **Audio:**
    - il gate onset conta tutti gli onset contro la griglia e solo il canale L (`metrics_audio.py:42-57`);
    - lo spettrogramma di `inspect` viene costruito su stereo interleaved (`cli.py:420`).

### Pipeline LLM
12. ✔ **Budget mai applicato** (`orchestrator/pipeline.py:31` fa `kw.pop("budget")`). `BudgetExceeded` non viene mai
    gestito, il report scrive 0 USD e la spesa viene salvata solo in S9.
13. ✔ **La scala dell'output strutturato non fa fallback.**
    - In `structured.py:53`, `client.chat` sta fuori dal `try`: un 4xx dello schema strict blocca la pipeline invece
      di passare al livello successivo.
    - `capabilities.py:70` fa `bool("auto")`, che vale `True`.
    - Lo schema pydantic grezzo non è compatibile con lo strict mode di OpenAI.
    - Il livello json_object non tollera i fence.
14. ✔ **`time.sleep` dentro `async achat`** (`client.py:235`).
15. **Resume non idempotente:**
    - S4–S7 non hanno un controllo per scena e vengono marcati come fatti dopo la prima scena (`pipeline.py:97-99,145`);
    - i log LLM vengono sovrascritti al resume (il contatore riparte da 0001);
    - il prompt non viene salvato prima di S0.
16. **L'ambiente di compilazione non è quello spedito:**
    - `common` viene tree-shakato solo da v1 (`pipeline.py:121-125`);
    - il math in S4/S5 ripiega su v1, mentre S9 usa la versione esatta (`steps.py:192-198` vs `384-387`);
    - il profilo per scena viene ignorato in S4–S6 (`steps.py:62,267`);
    - gli slot vengono abbinati per posizione e non per id (`steps.py:409`).
17. **Versioni:**
    - `revise` sovrascrive versioni esistenti (`version+1` calcolato dalla best, non dalla massima);
    - `select_best` ordina come stringhe (`v10<v2`), include `v1.math` e ha un anti-regressione debole.
18. **Robustezza:**
    - un envelope malformato in una scena fa perdere tutti i draft pagati, perché il gather avviene prima della
      scrittura su disco (`steps.py:146-166`);
    - nessun controllo su `finish_reason=="length"`;
    - `choices=None` solleva `TypeError` senza retry;
    - quando la compilazione della revise fallisce, viene riproposta la stessa critica.
19. **Il fixer riceve numeri di riga non rimappati** (header, common e math sono anteposti; `steps.py:217` tronca a
    4000 caratteri), e non può correggere errori in `style.glsl`.
20. **S0 non applica i flag della CLI** (bpm, profile, loop), e `min(duration, 120)` non tocca la timeline.

### Player
21. ✔ **`LINK_STATUS` non controllato** (`player/src/programs.ts:104-132`): un link fallito viene riportato
    `ok:true` con frame neri. Inoltre `vs`/`fs` non vengono mai cancellati.
22. **Canvas mai dimensionato:** `resize()` viene chiamato solo da `captureDataURL` (`player.ts:232-243`), quindi
    bundle ed embed restano a 300×150.
23. ✔ **`demogen play` fallisce sempre:** `player/index.html` non definisce `window.__demogen`, e si va in timeout
    dopo 15 s. Anche `browser/spike.py:15-16` usa un'API vecchia.
24. ✔ **`pause()` non salva `offsetS`:** alla ripresa la demo torna a 0. Con loop e audio attivi l'immagine si
    blocca a fine durata (`player.ts:177`).
25. **Audio:**
    - ritardo di almeno 80 ms, fino a circa 0,45 s dopo un seek;
    - `nextStartAt` non recupera gli underrun, quindi i chunk si sovrappongono (`audio.ts:198-245`);
    - il fallback RGBA8 decodifica rumore (`audio.ts:50` vs `165`);
    - il primo click nel bundle non sblocca l'audio, e gli errori di `load()` vengono ingoiati.
26. **Leak e ciclo di vita:**
    - `harness.ts:31-34` crea un `Player` nuovo a ogni `load()` senza fare dispose del precedente;
    - `dispose()` non libera programmi, FBO, VBO, listener né AudioContext;
    - il restore dopo una perdita di contesto duplica `AudioEngine`.
27. **Altro:**
    - collisione delle uniform location (`post.ts:94`);
    - la quality ladder non scende mai (`quality.ts:68-69`);
    - frame pacing sbagliato a 75/90/144 Hz;
    - durante una transizione la scena entrante riceve il tempo della uscente;
    - filtro NEAREST mai ripristinato;
    - `hasMap` con `vec2 map`;
    - `textLen` conta caratteri UTF-16 mentre il testo è codificato in UTF-8;
    - robustezza di `format.ts` (limite 1 MB mai applicato, `timeline.bpm` non validato, `in` sugli id).

### Tooling GLSL (Python)
28. **Minify a regex:** `b - -c` diventa `b--c`; i commenti a blocco vengono rimossi prima di quelli di riga e
    cancellano codice (`glsl/minify.py`).
29. **Treeshake:** importa la copia di libreria di funzioni che la scena definisce già (ridefinizione)
    (`glsl/treeshake.py:45`).
30. **Preprocessor:**
    - manca include-once;
    - un ciclo viene segnalato solo come "troppo profondo";
    - accetta path assoluti e `..`;
    - la `SourceMap` viene scartata.

### Oracolo matematico
31. ✔ **Il codegen produce GLSL non valido:**
    - `%` diventa `(x mod 2.0)` (`codegen.py:15`), che è un errore di sintassi;
    - `atan2` è in whitelist, ma GLSL ha solo `atan(y,x)`;
    - manca il controllo di arità (`len2(x,y,0.0)`, `min(a,b,c)`, `len2(x)`);
    - `norm2`/`norm3` mancano dalla tabella del runner.
32. ✔ **La verifica accetta claim non validi:**
    - un claim Lipschitz viene accettato anche senza alcun punto valutato, perché `max_ratio` resta 0
      (`verify.py:111-121`);
    - le coppie sono ripetute e lontane;
    - il controllo di segno della SDF richiede solo che esistano entrambi i segni;
    - vengono legati solo x, y e t, quindi nessuna SDF 3D è verificabile.
33. ✔ **La firma GLSL è in ordine alfabetico** (`oracle.py:56`) invece che nell'ordine di `inputs`. Inoltre:
    - `id` non viene validato;
    - la semantica Python differisce da GLSL (`fmod` invece di mod floored, `smoothstep` con estremi invertiti,
      `pow` con base negativa);
    - i rifiuti non tornano mai all'LLM;
    - `subprocess.run` blocca l'event loop.

### Libreria GLSL
34. **`gnoise` è discontinuo agli interi** (`noise.glsl:22-25`). Inoltre:
    - l'hash può restituire 1.0;
    - `chip.glsl` usa `fract(sin(...))` con argomenti grandi;
    - `calcAO` non ha il `/4.0`;
    - `beatFlash` non limita nulla.

### Test e CI
35. ✔ **Assert trasformati in skip:** `test_smoke.py:40-49`, `test_golden.py:36-41`, `test_e2e_fake.py:41-51` e
    `test_inspect.py:31-41` mettono `assert res["ok"]` dentro `try/except Exception: pytest.skip`.
36. **Altri problemi dei test:**
    - un golden mancante viene scritto e il test passa;
    - `test_math_oracle.py:79-86` è tautologico;
    - `importorskip("playwright")` in `test_audio.py` salta anche i test numpy puri;
    - l'import `tests.fake_openai` è fragile.
37. **Marker `live`/`perf`:** sono dichiarati ma non c'è `addopts`/`--strict-markers` e nessun test li usa. In CI
    manca `timeout-minutes`, e in Playwright manca un timeout di default.

### Docs vs codice
38. Il README è fermo alla Fase 0.
39. CLAUDE.md scrive `revise <scena> "nota"`, ma la CLI usa `--scene/--note`.
40. `docs/piano-esecuzione.md` dichiara come fatte cose che non lo sono:
    - resume idempotente;
    - stop a budget;
    - WCAG 2.3.1;
    - "claim falsi tutti rifiutati";
    - watchdog psutil con timeout a 5 s;
    - codegen sympy (`sympy`/`psutil` sono dipendenze mai importate);
    - test di scheduling con OfflineAudioContext.

---

## Batch da eseguire

### Batch B: integrità di test e CI
File: `tests/*.py`, `pyproject.toml`, `.github/workflows/ci.yml`, `demogen/browser/session.py`.
- Nei 4 test con il browser (#35), il `try/except → skip` deve coprire **solo** l'avvio di `Harness`; gli assert vanno
  fuori. Con `CI=true` niente skip: se il browser manca, il test fallisce.
- Golden mancante = test fallito, salvo `DEMOGEN_UPDATE_GOLDEN=1`.
- Sistemare il test tautologico e l'`importorskip` troppo largo.
- In `pyproject.toml`: `addopts = "-m 'not live and not perf' --strict-markers"`.
- In CI: `timeout-minutes: 20`.
- In `session.py`: `page.set_default_timeout` e una chiusura robusta di Playwright, anche se `launch()` o `goto`
  falliscono.
- Atteso: alcuni test diventeranno rossi, perché mettono a nudo bug reali (es. #21). Annotarli e risolverli nei batch
  F/G, oppure segnarli `xfail(strict=True)` con riferimento al punto di questo documento.

### Batch C: sicurezza
File: `bundle/build.py`, `project/store.py`, `orchestrator/steps.py`, `math/safe_parse.py`, `math/verify.py`.
- `html.escape` sul titolo; nel JSON incorporato, `</` → `<\/` e `<!--` → `<\!--`. Test con un payload malevolo.
- `slugify(spec.title)` per i nomi file; in `Project`, controllo che il path resti nel progetto
  (`resolve().is_relative_to(root)`).
- Runner con `[sys.executable, "-I", runner]`.
- Clamp lato server di `samples` (≤ 4096), `tol` e `tol_grad`, validati prima di costruire i punti.
- Network block con prefisso `base_url + "/"`.

### Batch D: correttezza della pipeline
File: `orchestrator/pipeline.py`, `steps.py`, `selection.py`, `llm/client.py`, `llm/structured.py`,
`llm/capabilities.py`.
- **Budget e chiamate LLM:**
  - passare `budget` nella factory;
  - `BudgetExceeded` → stop con la migliore versione;
  - spesa salvata in `state.json` a ogni step;
  - costo calcolato con l'id del modello configurato;
  - log LLM non sovrascritti (contatore che riprende o timestamp).
- **Output strutturato (#13):**
  - in `chat_structured`, un 4xx sul livello json_schema/json_object fa passare al livello successivo;
  - capability `"auto"` risolta davvero;
  - schema strict compatibile (`additionalProperties:false`, tutti i campi required), oppure niente strict;
  - parsing tollerante ai fence.
- **Async:** `achat` usa `await asyncio.sleep`; il subprocess dell'oracolo va in `asyncio.to_thread`.
- **Resume:** per scena, con un set `done_scenes` in `state.json`; prompt salvato prima di S0.
- **Compilazione coerente con ciò che si spedisce (#16):**
  - `common` ricalcolato per ogni versione;
  - un'unica funzione `math_for(scene, version)` usata da S4, S5 e S9;
  - profilo per scena in S4–S6;
  - slot abbinati per id, con validazione incrociata in `DemoSpec`.
- **Versioni:**
  - numero = massimo esistente + 1;
  - ordinamento numerico;
  - `*.math.glsl` esclusi;
  - anti-regressione rispetto al massimo.
- **Errori di envelope:** isolati per scena, con i draft scritti su disco appena arrivano; controlli su
  `finish_reason` e `choices`.
- **Blocker:** una versione con blocker non può diventare `accept`/best; S9 analizza il flash sulla demo intera e
  fallisce se ci sono blocker.
- **Fixer:** errori con le righe rimappate sulla scena usando un offset o `#line`.

### Batch E: gate del critic
File: `critic/flash.py`, `gates.py`, `metrics_video.py`, `metrics_audio.py`, `player/src/harness.ts`.
- **Flash:**
  - campionamento ≥ 30 fps su tutta la scena;
  - linearizzazione per pixel prima della media per cella;
  - area WCAG (circa 2,8% dello schermo, parametrizzata);
  - flash = coppia di transizioni opposte su una finestra mobile di 1 s;
  - regola del rosso a coppie.
- **Test sintetici per il flash:**
  - strobo a 8 Hz campionato come in produzione → bloccato;
  - flash su area parziale → bloccato;
  - flash a 2 Hz sul beat → deve passare.
- **Perf:** scalare per pixel (`res` del profilo / risoluzione misurata) oppure misurare alla risoluzione del budget.
  Con SwiftShader i gate realtime diventano `info` (come da piano §M0).
- **Flicker:** soglia compatibile con n campioni, misurata su diff tra frame realmente consecutivi.
- **Floor e audio:** collegare `floor_samples`; onset solo sui colpi forti, con mix L+R; spettrogramma mono.

### Batch F: player
File: `player/src/programs.ts`, `player.ts`, `audio.ts`, `harness.ts`, `post.ts`, `element.ts`, `player/index.html`,
`demogen/browser/spike.py`.
- **Shader:** `LINK_STATUS` verificato, anche dopo `COMPLETION_STATUS_KHR`, con il log; `deleteShader` dopo il link.
- **Canvas e tempo:**
  - `resize()` in `load`/`play` più un `ResizeObserver`;
  - `pause()` salva `offsetS`;
  - loop con audio.
- **Play e spike:** in `index.html` caricare l'harness oppure esporre `__demogen` in modalità play; aggiornare lo
  spike.
- **Audio:**
  - `startCtxTime` allineato all'inizio reale del primo chunk;
  - recupero di `nextStartAt` quando è nel passato;
  - fallback RGBA8 corretto;
  - unlock al primo click nel bundle, ed errori di `load()` mostrati.
- **Ciclo di vita:**
  - `dispose()` completo, con `AudioEngine.dispose`;
  - `harness.load()` fa dispose del player precedente;
  - restore dopo perdita di contesto senza duplicati.
- **Correzioni minori (#27):** uniform in `post.ts` indicizzate per programma (Map/WeakMap), quality ladder, pacing,
  tempo durante le transizioni, NEAREST/LINEAR, `textLen` in byte, limiti di `format.ts`.
- **Vincolo:** il player core deve restare ≤ 12 KB gzip (gate in `ci.yml`).

### Batch G: oracolo matematico e tooling GLSL
File: `math/codegen.py`, `safe_parse.py`, `verify.py`, `oracle.py`, `steps.py`, `glsl/minify.py`,
`glsl/treeshake.py`, `glsl/preprocessor.py`.
- **Codegen:**
  - `%` → `mod(a,b)`, `atan2` → `atan(y,x)`;
  - tabella di arità;
  - mod floored in Python come in GLSL; `smoothstep` come in GLSL; `norm2`/`norm3` sistemati o tolti.
- **Verifica:**
  - rifiuto se sono stati valutati meno di N punti;
  - coppie distinte e vicine;
  - segno della SDF verificato davvero;
  - binding di z e dei parametri.
- **Firma e rifiuti:** firma nell'ordine di `inputs`; `id` validato con `^[A-Za-z_]\w*$`; i rifiuti tornano all'LLM
  nel messaggio di revisione.
- **Test:** compilazione nel browser di ogni costrutto emesso dal codegen.
- **Minify:** basata su token, oppure correggere spazi tra operatori unari e l'ordine dei commenti.
- **Treeshake:** esclude i nomi definiti nella scena.
- **Preprocessor:** include-once, path confinati, `SourceMap` usata.
- **Libreria GLSL:** fix di `gnoise` e hash in [0,1); `chip.glsl` con hash intero.

### Batch H: docs
- README: setup aggiornato, config `demogen.yaml`, `generate`/`inspect`/`resume`.
- CLAUDE.md: sintassi di `revise`.
- `docs/piano-esecuzione.md`: riallineare le milestone dichiarate ✅ con lo stato reale (#40).
- Rimuovere `sympy`/`psutil` dalle dipendenze, oppure implementare il watchdog.

---

## Verifica (per ogni batch e finale)

- `py -m uv run ruff check .` e `py -m uv run pytest -q`. Dopo il Batch B gli skip devono comparire solo se il
  browser manca davvero.
- `npm run build`, `npm run typecheck --workspace player`, `npm test --workspace player` e il gate di dimensione del
  player (lo script è in `ci.yml`).
- E2E:
  - `py -m uv run demogen generate "plasma 8s" --project projects/t --fake --gpu swiftshader` deve produrre
    `.demo` e `.html` che compilano;
  - aprendo `out/*.html` il canvas è a tutto schermo, il click avvia l'audio e pause/play mantiene la posizione;
  - `py -m uv run demogen resume --project projects/t` non deve rifare chiamate LLM;
  - `py -m uv run demogen play examples/timeline.json` si apre senza timeout.
- Sicurezza: test con un titolo o un testo che contiene `</script>` e `../`.
- Prima di ogni push, grep della history per pattern di chiavi (`sk-…`, `ghp_…`, `AKIA…`, `BEGIN … PRIVATE KEY`),
  come da CLAUDE.md.

## Decisioni prese finora

- **Branch:** `fix/review-batch-a` creato sul posto invece di un worktree, perché il Batch A partiva dal WIP non
  committato.
- **Template unico:** `demogen/demo.yaml`; la copia in root `demogen.demo.yaml` è stata rimossa. La config si crea
  con `demogen init` invece che con `cp`.
- **Flag di Typer:** `pretty_exceptions_show_locals=False` è esplicito anche se Typer 0.29 lo ha già come default,
  perché `pyproject.toml` ammette `typer>=0.12`. La protezione vera è `SecretStr`.
- **Ruolo mancante:** ora solleva `ValueError` con un messaggio chiaro invece di un `KeyError`; nessun chiamante
  intercettava `KeyError`.
