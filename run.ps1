<#
.SYNOPSIS
    Menu di demogen: genera demo, lancia gli esempi, setup e test, chiude i processi rimasti aperti.

.DESCRIPTION
    Avvio:    .\run.ps1                 (oppure doppio click su run.cmd)
    Diretto:  .\run.ps1 -Action <nome>  esegue una voce senza menu, con i valori di default
              es.  .\run.ps1 -Action processi
                   .\run.ps1 -Action chiudi -Yes
                   .\run.ps1 -Action m1
    Elenco:   .\run.ps1 -Action elenco

    Ogni voce chiama la CLI reale (uv run demogen ...) dalla cartella del repo.
    Compatibile con Windows PowerShell 5.1 e PowerShell 7.

.PARAMETER Action
    Nome o numero di una voce: la esegue e termina. Le domande prendono il valore di default.
.PARAMETER Yes
    Con -Action: risponde sì alle conferme (chiudere i processi, aprire il browser, spendere sull'LLM).
#>
[CmdletBinding()]
param(
    [string]$Action = "",
    [switch]$Yes
)

$ErrorActionPreference = "Stop"

$Repo = $PSScriptRoot
$Venv = Join-Path $Repo ".venv"
$script:NonInteractive = ($Action -ne "")
$script:AutoYes = [bool]$Yes
$script:LastExit = 0
$script:UvCmd = $null

# ------------------------------------------------------------------ output

function Write-Title([string]$Text) { Write-Host ""; Write-Host ("  " + $Text) -ForegroundColor Cyan }
function Write-Note([string]$Text) { Write-Host $Text -ForegroundColor DarkGray }
function Write-Ok([string]$Text) { Write-Host $Text -ForegroundColor Green }
function Write-Attention([string]$Text) { Write-Host $Text -ForegroundColor Yellow }
function Write-Err([string]$Text) { Write-Host $Text -ForegroundColor Red }

function Stop-Cancelled([string]$Why = "annullato") {
    Write-Note ("  " + $Why)
    if ($script:NonInteractive) { $script:LastExit = 1 }
}

# ------------------------------------------------------------------ input

function Read-Value([string]$Label, [string]$Default = "") {
    if ($script:NonInteractive) { return $Default }
    $hint = ""
    if ($Default -ne "") { $hint = " [" + $Default + "]" }
    $v = Read-Host ("  " + $Label + $hint)
    if ($null -eq $v) { $v = "" }
    $v = $v.Trim()
    if ($v -eq "") { return $Default }
    return $v
}

function Confirm-Choice([string]$Question, [bool]$Default = $true) {
    # senza menu decide solo -Yes: nessuna spesa o chiusura implicita
    if ($script:NonInteractive) { return $script:AutoYes }
    $hint = "[S/n]"
    if (-not $Default) { $hint = "[s/N]" }
    $v = Read-Host ("  " + $Question + " " + $hint)
    if ([string]::IsNullOrWhiteSpace($v)) { return $Default }
    return (@("s", "si", "sì", "y", "yes") -contains $v.Trim().ToLowerInvariant())
}

function Read-Choice([string]$Label, [string[]]$Options, [string]$Default) {
    while ($true) {
        $v = Read-Value ($Label + " (" + ($Options -join " / ") + ")") $Default
        if ($Options -contains $v) { return $v }
        $n = 0
        if ([int]::TryParse($v, [ref]$n) -and $n -ge 1 -and $n -le $Options.Count) { return $Options[$n - 1] }
        $pref = @($Options | Where-Object { $v -ne "" -and $_.StartsWith($v) })
        if ($pref.Count -eq 1) { return $pref[0] }
        if ($script:NonInteractive) { throw ("valore non valido per '" + $Label + "': " + $v) }
        Write-Attention ("  scegli tra: " + ($Options -join ", "))
    }
}

function Read-Number([string]$Label, [string]$Default, [double]$Min, [double]$Max) {
    $inv = [Globalization.CultureInfo]::InvariantCulture
    while ($true) {
        $v = (Read-Value $Label $Default).Replace(",", ".")
        $d = 0.0
        if ([double]::TryParse($v, [Globalization.NumberStyles]::Float, $inv, [ref]$d) -and $d -ge $Min -and $d -le $Max) {
            return $d.ToString($inv)
        }
        if ($script:NonInteractive) { throw ("valore non valido per '" + $Label + "': " + $v) }
        Write-Attention ("  serve un numero tra " + $Min + " e " + $Max)
    }
}

function Select-Item([string]$Title, [object[]]$Items, [scriptblock]$Label, [switch]$AllowPath) {
    if ($null -eq $Items -or $Items.Count -eq 0) { return $null }
    Write-Host ("  " + $Title)
    for ($i = 0; $i -lt $Items.Count; $i++) {
        Write-Host ("   {0,2})  {1}" -f ($i + 1), (& $Label $Items[$i]))
    }
    if ($script:NonInteractive) { return $Items[0] }
    while ($true) {
        $v = Read-Value "Scelta (vuoto = annulla)" ""
        if ($v -eq "") { return $null }
        $n = 0
        if ([int]::TryParse($v, [ref]$n) -and $n -ge 1 -and $n -le $Items.Count) { return $Items[$n - 1] }
        if ($AllowPath -and (Test-Path -LiteralPath $v)) { return (Resolve-Path -LiteralPath $v).Path }
        Write-Attention "  scelta non valida"
    }
}

# ------------------------------------------------------------------ esecuzione dei comandi

function Format-Argument([string]$Value) {
    # quoting di CommandLineToArgvW: Start-Process di PowerShell 5.1 non quota gli argomenti
    if ($Value -eq "") { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }
    $s = [regex]::Replace($Value, '(\\*)"', { param($m) ($m.Groups[1].Value * 2) + '\"' })
    $s = [regex]::Replace($s, '(\\+)$', { param($m) $m.Groups[1].Value * 2 })
    return '"' + $s + '"'
}

function Invoke-Tool([string]$Exe, [string[]]$Arguments) {
    $line = (@($Arguments) | ForEach-Object { Format-Argument $_ }) -join " "
    Write-Note ("  > " + [IO.Path]::GetFileNameWithoutExtension($Exe) + " " + $line)
    # Start-Process collega il processo direttamente alla console: colori, output dal vivo, input
    $p = Start-Process -FilePath $Exe -ArgumentList $line -WorkingDirectory $Repo -NoNewWindow -Wait -PassThru
    $code = $p.ExitCode
    if ($null -eq $code) { $code = 0 }
    $script:LastExit = $code
    if ($code -ne 0) { Write-Err ("  terminato con codice " + $code); return $false }
    return $true
}

function Resolve-Uv {
    if ($null -ne $script:UvCmd) { return }
    $c = Get-Command uv -ErrorAction SilentlyContinue
    if ($c) { $script:UvCmd = @($c.Source); return }
    $local = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path $local) { $script:UvCmd = @($local); return }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { $script:UvCmd = @($py.Source, "-m", "uv"); return }
    throw "uv non trovato: installalo (https://docs.astral.sh/uv/) oppure con 'py -m pip install uv'"
}

function Invoke-Uv([string[]]$Arguments) {
    Resolve-Uv
    $pre = @()
    if ($script:UvCmd.Count -gt 1) { $pre = $script:UvCmd[1..($script:UvCmd.Count - 1)] }
    return (Invoke-Tool $script:UvCmd[0] (@($pre) + @($Arguments)))
}

function Invoke-Demogen([string[]]$Arguments) { return (Invoke-Uv (@("run", "demogen") + @($Arguments))) }

function Invoke-Npm([string[]]$Arguments) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm non trovato: installa Node.js (https://nodejs.org)" }
    return (Invoke-Tool $env:ComSpec (@("/c", "npm") + @($Arguments)))
}

# ------------------------------------------------------------------ utilità

function Resolve-RepoPath([string]$Path) {
    if ([IO.Path]::IsPathRooted($Path)) { return $Path }
    return (Join-Path $Repo $Path)
}

function Get-RelativePath([string]$Path) {
    if ($Path.StartsWith($Repo + "\")) { return $Path.Substring($Repo.Length + 1) }
    return $Path
}

function Get-Slug([string]$Text) {
    $n = $Text.ToLowerInvariant().Normalize([Text.NormalizationForm]::FormD)
    $chars = $n.ToCharArray() | Where-Object {
        [Globalization.CharUnicodeInfo]::GetUnicodeCategory($_) -ne [Globalization.UnicodeCategory]::NonSpacingMark
    }
    $s = [regex]::Replace((-join $chars), '[^a-z0-9]+', '-').Trim('-')
    if ($s.Length -gt 30) { $s = $s.Substring(0, 30).Trim('-') }
    if ($s -eq "") { $s = "demo" }
    return $s
}

function Get-BudgetCap {
    # legge solo il tetto di spesa: demogen.yaml contiene la chiave e non va mai stampato
    $cfg = Join-Path $Repo "demogen.yaml"
    if (-not (Test-Path $cfg)) { return $null }
    $m = Select-String -Path $cfg -Pattern '^\s*max_total_cost_usd:\s*([0-9.]+)' | Select-Object -First 1
    if ($m) { return $m.Matches[0].Groups[1].Value }
    return "?"
}

function Test-PlayerBuilt { return (Test-Path (Join-Path $Repo "player\dist\demogen-player.min.js")) }

function Confirm-PlayerBuilt {
    if (Test-PlayerBuilt) { return $true }
    Write-Attention "  il player non è compilato (manca player\dist)"
    if (Confirm-Choice "Lo compilo ora (npm run build)?" $true) { return (Invoke-Npm @("run", "build")) }
    return $false
}

function Open-Newest([string]$Dir, [string]$Filter, [string]$What, [switch]$Directory) {
    if (-not (Test-Path $Dir)) { return }
    if ($Directory) {
        $item = Get-ChildItem $Dir -Directory -Filter $Filter | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    } else {
        $item = Get-ChildItem $Dir -File -Filter $Filter | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }
    if ($null -eq $item) { return }
    Write-Ok ("  " + $What + ": " + $item.FullName)
    if (Confirm-Choice "Aprire?" $true) { Invoke-Item -LiteralPath $item.FullName }
}

# ------------------------------------------------------------------ progetti ed esempi

function Get-ProjectLabel([string]$Dir) {
    $label = Split-Path $Dir -Leaf
    try {
        $spec = Join-Path $Dir "spec.json"
        if (Test-Path $spec) {
            $t = (Get-Content $spec -Raw -Encoding UTF8 | ConvertFrom-Json).title
            if ($t) { $label += "  -  " + $t }
        }
        $st = Get-Content (Join-Path $Dir "state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        $stato = "incompleto"
        if (@($st.done) -contains "S9") { $stato = "completo" }
        if ($st.stopped) { $stato = "fermato (" + $st.stopped + ")" }
        $label += "  [" + $stato
        if ($st.budget_spent_usd) { $label += (", {0:N3} USD" -f [double]$st.budget_spent_usd) }
        $label += "]"
    } catch { }
    return $label
}

function Select-Project {
    $base = Join-Path $Repo "projects"
    $dirs = @()
    if (Test-Path $base) {
        $dirs = @(Get-ChildItem $base -Directory |
            Where-Object { Test-Path (Join-Path $_.FullName "state.json") } |
            Sort-Object LastWriteTime -Descending | ForEach-Object { $_.FullName })
    }
    if ($dirs.Count -eq 0) {
        Write-Note "  nessun progetto in projects\ (nascono con le voci 1 e 2)"
        $p = Read-Value "Percorso di un progetto (vuoto = annulla)" ""
        if ($p -eq "") { return $null }
        $p = Resolve-RepoPath $p
    } else {
        $p = Select-Item "Progetto (numero, o percorso di un'altra cartella):" $dirs { param($d) Get-ProjectLabel $d } -AllowPath
        if ($null -eq $p) { return $null }
    }
    if (-not (Test-Path (Join-Path $p "state.json"))) {
        Write-Attention ("  " + $p + " non è un progetto demogen (manca state.json)")
        return $null
    }
    return $p
}

function Get-Examples([switch]$Shaders) {
    $ex = Join-Path $Repo "examples"
    # la demo principale per prima
    Get-ChildItem $ex -Recurse -File -Filter "*timeline*.json" |
        Sort-Object @{ Expression = { $_.Name -ne "timeline.json" } }, FullName |
        ForEach-Object { $_.FullName }
    if ($Shaders) {
        # solo shader video: gli shader audio (mainAudio) non si aprono da soli
        Get-ChildItem (Join-Path $ex "shaders") -File -Filter "*.glsl" |
            Where-Object { Select-String -LiteralPath $_.FullName -Pattern "mainImage" -Quiet } |
            ForEach-Object { $_.FullName }
    }
}

function Select-Example([switch]$Shaders) {
    $items = @(Get-Examples -Shaders:$Shaders)
    return (Select-Item "Esempio:" $items { param($f) Get-RelativePath $f })
}

function Open-ProjectDemo([string]$Project) {
    $html = $null
    $out = Join-Path $Project "out"
    if (Test-Path $out) {
        $html = Get-ChildItem $out -File -Filter "*.html" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }
    if ($null -eq $html) { Write-Attention ("  nessuna demo in " + $out + " (la generazione è arrivata al bundle?)"); return }
    Write-Ok ("  demo: " + $html.FullName)
    if (Confirm-Choice "Aprirla nel browser? (click per avviare, spazio = pausa)" $true) {
        Invoke-Item -LiteralPath $html.FullName
    }
}

# ------------------------------------------------------------------ processi

function Get-DemogenProcesses {
    $venvRx = [regex]::Escape($Venv)
    $repoRx = [regex]::Escape($Repo)
    $all = @(Get-CimInstance Win32_Process)
    $byId = @{}
    $byParent = @{}
    foreach ($p in $all) {
        $byId[[int]$p.ProcessId] = $p
        $k = [int]$p.ParentProcessId
        if (-not $byParent.ContainsKey($k)) { $byParent[$k] = New-Object System.Collections.ArrayList }
        [void]$byParent[$k].Add($p)
    }
    $found = @{}
    foreach ($p in $all) {
        $id = [int]$p.ProcessId
        if ($id -eq $PID) { continue }
        $exe = [string]$p.ExecutablePath
        $cmd = [string]$p.CommandLine
        $kind = $null
        # Chromium di Playwright (non quello del plugin MCP del browser)
        if ((($exe + " " + $cmd) -match "ms-playwright") -and ($cmd -notmatch "mcp-chrome")) { $kind = "browser Playwright" }
        # python del venv: il trampolino in .venv e l'interprete vero, che ha il venv nella riga di comando
        elseif (($exe -match ("^" + $venvRx)) -or ($cmd -match $venvRx)) { $kind = "python demogen" }
        elseif (($p.Name -eq "node.exe") -and ($cmd -match $repoRx) -and ($cmd -match "vitest|esbuild")) { $kind = "node (player)" }
        if ($kind) { $found[$id] = $kind }
    }
    # discendenti: sottoprocessi dell'oracolo, driver di Playwright, finestre del browser
    $queue = New-Object System.Collections.Queue
    foreach ($id in @($found.Keys)) { $queue.Enqueue($id) }
    while ($queue.Count -gt 0) {
        $id = $queue.Dequeue()
        if (-not $byParent.ContainsKey($id)) { continue }
        foreach ($c in $byParent[$id]) {
            $cid = [int]$c.ProcessId
            if ($found.ContainsKey($cid) -or $cid -eq $PID -or $c.Name -eq "conhost.exe") { continue }
            # PID riusato: un figlio non può essere nato prima del padre
            if ($c.CreationDate -lt $byId[$id].CreationDate) { continue }
            $found[$cid] = $found[$id]
            $queue.Enqueue($cid)
        }
    }
    foreach ($id in ($found.Keys | Sort-Object)) {
        $p = $byId[$id]
        $cmd = [string]$p.CommandLine
        if ($cmd.Length -gt 90) { $cmd = $cmd.Substring(0, 87) + "..." }
        [pscustomobject]@{
            PID     = $id
            Tipo    = $found[$id]
            Nome    = $p.Name
            MB      = [int]([double]$p.WorkingSetSize / 1MB)
            Comando = $cmd
        }
    }
}

function Show-DemogenProcesses([object[]]$List) {
    if ($List.Count -eq 0) { Write-Ok "  nessun processo di demogen attivo"; return }
    $List | Format-Table PID, Tipo, Nome, MB, Comando -AutoSize | Out-String -Width 200 | Write-Host
    $mb = ($List | Measure-Object MB -Sum).Sum
    Write-Host ("  {0} processi, {1} MB in tutto" -f $List.Count, $mb)
}

# ------------------------------------------------------------------ voci del menu

function Invoke-Generate([switch]$Fake) {
    if ($Fake) {
        Write-Title "Genera una demo finta (--fake): nessuna chiamata API, controlli veri nel browser"
        $defPrompt = "plasma neon che pulsa sul kick"; $defDur = "8"; $defBpm = "120"
    } else {
        Write-Title "Genera una demo con l'LLM"
        $cap = Get-BudgetCap
        if ($null -eq $cap) { Write-Attention "  manca demogen.yaml: crealo con la voce 14 (Config LLM)"; Stop-Cancelled ""; return }
        Write-Note ("  tetto di spesa in demogen.yaml: " + $cap + " USD")
        $defPrompt = ""; $defDur = "30"; $defBpm = "128"
    }
    $prompt = Read-Value "Prompt (vuoto = annulla)" $defPrompt
    if ($prompt -eq "") { Stop-Cancelled; return }
    $prompt = $prompt.Replace('"', "'")
    $dur = Read-Number "Durata in secondi (4-120)" $defDur 4 120
    $bpm = Read-Number "BPM (60-200)" $defBpm 60 200
    $prof = Read-Choice "Profilo" @("modern", "retro") "modern"
    $gpu = Read-Choice "GPU per i controlli (hardware = perf vere)" @("swiftshader", "hardware") "swiftshader"
    $defProj = "projects\" + (Get-Date -Format "yyyyMMdd-HHmmss") + "_" + (Get-Slug $prompt)
    $proj = Read-Value "Cartella del progetto" $defProj
    $cli = @("generate", $prompt, "--duration", $dur, "--bpm", $bpm, "--profile", $prof, "--gpu", $gpu, "--project", $proj)
    if ($Fake) {
        $cli += "--fake"
    } elseif (-not (Confirm-Choice ("Avvio? Le chiamate all'LLM costano (tetto " + $cap + " USD)") $true)) {
        Stop-Cancelled; return
    }
    if (Invoke-Demogen $cli) { Open-ProjectDemo (Resolve-RepoPath $proj) }
}

function Invoke-Resume {
    Write-Title "Riprendi un progetto: rifà solo i passi mancanti, senza ripetere le chiamate già fatte"
    $p = Select-Project
    if ($null -eq $p) { Stop-Cancelled; return }
    $llm = Read-Choice "LLM" @("reale", "finto") "reale"
    $gpu = Read-Choice "GPU per i controlli" @("swiftshader", "hardware") "swiftshader"
    $cli = @("resume", $p, "--gpu", $gpu)
    if ($llm -eq "finto") { $cli += "--fake" }
    if (Invoke-Demogen $cli) { Open-ProjectDemo $p }
}

function Invoke-Revise {
    Write-Title "Revisiona una scena: nuova versione guidata da una tua nota"
    $p = Select-Project
    if ($null -eq $p) { Stop-Cancelled; return }
    $sdir = Join-Path $p "scenes"
    $scenes = @()
    if (Test-Path $sdir) { $scenes = @(Get-ChildItem $sdir -Directory | Sort-Object Name | ForEach-Object { $_.Name }) }
    if ($scenes.Count -eq 0) { Write-Attention "  il progetto non ha ancora scene"; Stop-Cancelled ""; return }
    foreach ($s in $scenes) {
        $info = "nessuna versione scelta"
        $best = Join-Path $sdir ($s + "\best.json")
        if (Test-Path $best) {
            try { $b = Get-Content $best -Raw | ConvertFrom-Json; $info = "migliore " + $b.version + ", punteggio " + $b.score } catch { }
        }
        Write-Host ("   " + $s + ": " + $info)
    }
    $scene = Read-Choice "Scena" $scenes $scenes[0]
    $note = Read-Value "Nota (es. meno nebbia, più contrasto sul kick; vuoto = annulla)" ""
    if ($note -eq "") { Stop-Cancelled; return }
    $llm = Read-Choice "LLM" @("reale", "finto") "reale"
    $gpu = Read-Choice "GPU per i controlli" @("swiftshader", "hardware") "swiftshader"
    $cli = @("revise", $p, "--scene", $scene, "--note", $note.Replace('"', "'"), "--gpu", $gpu)
    if ($llm -eq "finto") { $cli += "--fake" }
    if (Invoke-Demogen $cli) { Open-ProjectDemo $p }
}

function Invoke-Report {
    Write-Title "Report di un progetto"
    $p = Select-Project
    if ($null -eq $p) { Stop-Cancelled; return }
    [void](Invoke-Demogen @("report", $p))
}

function Invoke-OpenDemo {
    Write-Title "Apri la demo di un progetto"
    $p = Select-Project
    if ($null -eq $p) { Stop-Cancelled; return }
    Open-ProjectDemo $p
}

function Invoke-PlayMain {
    Write-Title "Demo principale (examples\timeline.json) in tempo reale"
    Write-Note "  si apre una finestra del browser: chiudila per tornare al menu"
    [void](Invoke-Demogen @("play", "examples\timeline.json", "--gpu", "auto"))
}

function Invoke-PlayExample {
    Write-Title "Play di un esempio in tempo reale"
    $f = Select-Example -Shaders
    if ($null -eq $f) { Stop-Cancelled; return }
    $gpu = Read-Choice "GPU" @("auto", "hardware", "swiftshader") "auto"
    Write-Note "  si apre una finestra del browser: chiudila per tornare al menu"
    [void](Invoke-Demogen @("play", (Get-RelativePath $f), "--gpu", $gpu))
}

function Invoke-Inspect {
    Write-Title "Inspect: metriche, controlli (flash, perf, NaN...) e fogli immagine in out\"
    $f = Select-Example -Shaders
    if ($null -eq $f) { Stop-Cancelled; return }
    $gpu = Read-Choice "GPU" @("swiftshader", "hardware") "swiftshader"
    if (Invoke-Demogen @("inspect", (Get-RelativePath $f), "--gpu", $gpu, "--out", "out")) {
        Open-Newest (Join-Path $Repo "out") "inspect_*" "report" -Directory
    }
}

function Invoke-Bundle {
    Write-Title "Bundle di un esempio: .demo + .html autonomo in out\"
    $f = Select-Example
    if ($null -eq $f) { Stop-Cancelled; return }
    if (Invoke-Demogen @("bundle", (Get-RelativePath $f), "--out", "out")) {
        Open-Newest (Join-Path $Repo "out") "*.html" "pagina"
    }
}

function Invoke-WebExamples {
    Write-Title "Esempi web del player (examples\web, funzionano anche da file)"
    if (-not (Confirm-PlayerBuilt)) { Stop-Cancelled ""; return }
    $pages = @(Get-ChildItem (Join-Path $Repo "examples\web") -File -Filter "*.html" | ForEach-Object { $_.FullName })
    $f = Select-Item "Pagina:" $pages { param($x) Split-Path $x -Leaf }
    if ($null -eq $f) { Stop-Cancelled; return }
    Invoke-Item -LiteralPath $f
}

function Invoke-Setup {
    Write-Title "Setup completo"
    if (-not (Invoke-Uv @("sync"))) { return }
    if (-not (Invoke-Uv @("run", "playwright", "install", "chromium"))) { return }
    if (-not (Invoke-Npm @("install"))) { return }
    if (Invoke-Npm @("run", "build")) { Write-Ok "  setup completato" }
}

function Invoke-Doctor {
    Write-Title "Doctor: ambiente e renderer GPU/CPU"
    [void](Invoke-Demogen @("doctor"))
}

function Invoke-Config {
    Write-Title "Configurazione LLM"
    $cfg = Join-Path $Repo "demogen.yaml"
    if (Test-Path $cfg) { Write-Note ("  demogen.yaml presente (tetto di spesa " + (Get-BudgetCap) + " USD); è in .gitignore") }
    else { Write-Attention "  demogen.yaml non c'è ancora" }
    $what = Read-Choice "Cosa faccio" @("crea", "modifica", "prova") "prova"
    switch ($what) {
        "crea" { [void](Invoke-Demogen @("init")) }
        "modifica" {
            if (-not (Test-Path $cfg)) { [void](Invoke-Demogen @("init")) }
            Write-Note "  chiave in providers.openrouter.api_key, modelli in roles, tetto in budget"
            Start-Process notepad.exe -ArgumentList (Format-Argument $cfg)
        }
        "prova" {
            Write-Note "  una chiamata minima per ruolo (testo, vision, json): costa pochi centesimi"
            if (Confirm-Choice "Procedo?" $true) { [void](Invoke-Demogen @("models", "check")) } else { Stop-Cancelled }
        }
    }
}

function Invoke-Tests {
    Write-Title "Test Python: ruff + pytest (la suite completa con il browser dura qualche minuto)"
    $k = Read-Value "Filtro pytest -k (vuoto = tutti)" ""
    if (-not (Invoke-Uv @("run", "ruff", "check", "."))) { return }
    $cli = @("run", "pytest", "-q")
    if ($k -ne "") { $cli += @("-k", $k) }
    if (Invoke-Uv $cli) { Write-Ok "  test verdi" }
}

function Invoke-PlayerTests {
    Write-Title "Test del player: typecheck + vitest + build"
    if (-not (Invoke-Npm @("run", "typecheck", "--workspace", "player"))) { return }
    if (-not (Invoke-Npm @("test", "--workspace", "player"))) { return }
    if (Invoke-Npm @("run", "build")) { Write-Ok "  player verde e compilato" }
}

function Invoke-Calibrate {
    Write-Title "Calibrate: ms per frame degli shader di esempio a 1920x1080 sulla GPU"
    if (Invoke-Demogen @("calibrate", "--gpu", "hardware", "--out", "out")) {
        $j = Join-Path $Repo "out\calibrate.json"
        if (Test-Path $j) { Get-Content $j -Raw | Write-Host }
    }
}

function Invoke-ShowProcesses {
    Write-Title "Processi di demogen attivi"
    Show-DemogenProcesses @(Get-DemogenProcesses)
}

function Invoke-KillProcesses {
    Write-Title "Chiudi i processi di demogen"
    Write-Note "  browser di Playwright, python del venv (CLI, test, oracolo), node di vitest/esbuild e i loro figli"
    Write-Note "  il tuo Chrome e gli altri programmi non vengono toccati"
    $list = @(Get-DemogenProcesses)
    Show-DemogenProcesses $list
    if ($list.Count -eq 0) { return }
    if (-not (Confirm-Choice ("Chiudo questi " + $list.Count + " processi?") $false)) { Stop-Cancelled; return }
    foreach ($p in $list) {
        try { Stop-Process -Id $p.PID -Force -ErrorAction Stop } catch { }  # già terminato con il padre
    }
    Start-Sleep -Milliseconds 800
    $left = @(Get-DemogenProcesses)
    if ($left.Count -eq 0) { Write-Ok ("  chiusi " + $list.Count + " processi") }
    else { Write-Attention ("  ancora attivi: " + $left.Count); Show-DemogenProcesses $left; $script:LastExit = 1 }
}

# ------------------------------------------------------------------ menu

$Menu = @(
    @{ Key = "1";  Name = "genera";      Section = "PRINCIPALE";   Label = "Genera una demo con l'LLM (OpenRouter, costa)"; Run = { Invoke-Generate } }
    @{ Key = "2";  Name = "finta";       Section = "PRINCIPALE";   Label = "Genera una demo finta (--fake, nessuna API)"; Run = { Invoke-Generate -Fake } }
    @{ Key = "3";  Name = "riprendi";    Section = "PRINCIPALE";   Label = "Riprendi un progetto interrotto (resume)"; Run = { Invoke-Resume } }
    @{ Key = "4";  Name = "revisiona";   Section = "PRINCIPALE";   Label = "Revisiona una scena con una nota (revise)"; Run = { Invoke-Revise } }
    @{ Key = "5";  Name = "report";      Section = "PRINCIPALE";   Label = "Mostra il report di un progetto"; Run = { Invoke-Report } }
    @{ Key = "6";  Name = "apri";        Section = "PRINCIPALE";   Label = "Apri nel browser la demo di un progetto"; Run = { Invoke-OpenDemo } }
    @{ Key = "7";  Name = "m1";          Section = "ESEMPI";       Label = "Demo principale in tempo reale (examples\timeline.json)"; Run = { Invoke-PlayMain } }
    @{ Key = "8";  Name = "play";        Section = "ESEMPI";       Label = "Play di un esempio a scelta (timeline o shader)"; Run = { Invoke-PlayExample } }
    @{ Key = "9";  Name = "inspect";     Section = "ESEMPI";       Label = "Inspect di un esempio: metriche, controlli e fogli in out\"; Run = { Invoke-Inspect } }
    @{ Key = "10"; Name = "bundle";      Section = "ESEMPI";       Label = "Bundle di un esempio (.demo + .html in out\)"; Run = { Invoke-Bundle } }
    @{ Key = "11"; Name = "web";         Section = "ESEMPI";       Label = "Esempi web del player (examples\web)"; Run = { Invoke-WebExamples } }
    @{ Key = "12"; Name = "setup";       Section = "SETUP E TEST"; Label = "Setup completo (uv sync, Chromium, npm install, build)"; Run = { Invoke-Setup } }
    @{ Key = "13"; Name = "doctor";      Section = "SETUP E TEST"; Label = "Doctor: ambiente e renderer GPU/CPU"; Run = { Invoke-Doctor } }
    @{ Key = "14"; Name = "config";      Section = "SETUP E TEST"; Label = "Config LLM: crea o modifica demogen.yaml, prova i modelli"; Run = { Invoke-Config } }
    @{ Key = "15"; Name = "test";        Section = "SETUP E TEST"; Label = "Test Python (ruff + pytest)"; Run = { Invoke-Tests } }
    @{ Key = "16"; Name = "test-player"; Section = "SETUP E TEST"; Label = "Test del player (typecheck + vitest + build)"; Run = { Invoke-PlayerTests } }
    @{ Key = "17"; Name = "calibrate";   Section = "SETUP E TEST"; Label = "Calibrate: ms degli shader di esempio sulla GPU"; Run = { Invoke-Calibrate } }
    @{ Key = "18"; Name = "processi";    Section = "PROCESSI";     Label = "Mostra i processi di demogen ancora attivi"; Run = { Invoke-ShowProcesses } }
    @{ Key = "19"; Name = "chiudi";      Section = "PROCESSI";     Label = "Chiudi i processi di demogen (browser, python, node)"; Run = { Invoke-KillProcesses } }
)

function Show-Header {
    Clear-Host
    Write-Host "  =========================================================" -ForegroundColor DarkCyan
    Write-Host "    demogen  -  menu" -ForegroundColor Cyan
    Write-Host "  =========================================================" -ForegroundColor DarkCyan
    $parts = @()
    if (Test-Path (Join-Path $Venv "Scripts\python.exe")) { $parts += "venv ok" } else { $parts += "venv MANCANTE (12)" }
    if (Test-PlayerBuilt) { $parts += "player ok" } else { $parts += "player da compilare (12)" }
    $cap = Get-BudgetCap
    if ($null -eq $cap) { $parts += "demogen.yaml MANCANTE (14)" } else { $parts += ("LLM: tetto " + $cap + " USD") }
    $n = 0
    try { $n = @(Get-DemogenProcesses).Count } catch { }
    if ($n -gt 0) { $parts += ("" + $n + " processi attivi (18/19)") }
    Write-Host ("    " + ($parts -join "  |  ")) -ForegroundColor DarkGray
}

function Show-Menu {
    Show-Header
    $section = ""
    foreach ($e in $Menu) {
        if ($e.Section -ne $section) {
            $section = $e.Section
            Write-Host ""
            Write-Host ("  " + $section) -ForegroundColor Yellow
        }
        Write-Host ("   {0,2})  {1}" -f $e.Key, $e.Label)
    }
    Write-Host ""
    Write-Host "    0)  Esci"
    Write-Host ""
}

function Find-Entry([string]$Choice) {
    $c = $Choice.Trim().ToLowerInvariant()
    foreach ($e in $Menu) { if ($e.Key -eq $c -or $e.Name -eq $c) { return $e } }
    return $null
}

function Invoke-Entry($Entry) {
    $script:LastExit = 0
    try {
        & $Entry.Run
    } catch {
        Write-Err ("  errore: " + $_.Exception.Message)
        $script:LastExit = 1
    }
}

$exitCode = 0
Push-Location $Repo
try {
    if ($script:NonInteractive) {
        if (@("elenco", "list", "?") -contains $Action.ToLowerInvariant()) {
            foreach ($e in $Menu) { Write-Host ("{0,3}  {1,-12} {2}" -f $e.Key, $e.Name, $e.Label) }
        } else {
            $entry = Find-Entry $Action
            if ($null -eq $entry) {
                Write-Err ("azione sconosciuta: " + $Action + "  (elenco: .\run.ps1 -Action elenco)")
                $exitCode = 2
            } else {
                Invoke-Entry $entry
                $exitCode = $script:LastExit
            }
        }
    } else {
        while ($true) {
            Show-Menu
            $choice = Read-Host "  Scelta"
            if ($null -eq $choice) { break }
            if (@("0", "q", "esci") -contains $choice.Trim().ToLowerInvariant()) { break }
            $entry = Find-Entry $choice
            if ($null -eq $entry) { continue }
            Invoke-Entry $entry
            Write-Host ""
            [void](Read-Host "  Invio per tornare al menu")
        }
    }
} finally {
    Pop-Location
}
exit $exitCode
