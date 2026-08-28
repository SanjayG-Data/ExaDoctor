# install.ps1 -- ExaDoctor one-command installer (Windows PowerShell).
#
#   irm https://raw.githubusercontent.com/SanjayG-Data/ExaDoctor/main/install.ps1 | iex
#
# PowerShell counterpart to install.sh -- same four steps, same behavior,
# adapted to PowerShell idioms instead of POSIX sh. install.sh cannot be
# used directly in native PowerShell (no `sh`, and `curl`/`iwr` isn't a
# drop-in replacement for `curl | sh`), which most Windows users hit on
# their very first try -- this script exists so that isn't a dead end.
#
# What it does, in order:
#   1. checks for git (needed to fetch the source; curl/Invoke-RestMethod
#      is always available as a PowerShell cmdlet, so no separate check)
#   2. installs uv if it isn't already on this machine, via the official
#      Astral installer (https://docs.astral.sh/uv/) -- uv is a real,
#      persistent prerequisite (ExaDoctor is a Python + pyexasol tool, not
#      a shell script), so this step makes it invisible rather than
#      pretending it isn't needed
#   3. runs `uv tool install` against the ExaDoctor source, which resolves
#      pyexasol/click into an isolated environment and installs a
#      standalone `exadoctor` command -- no `uv run`, no venv activation,
#      no uv at all needed to use it afterward
#   4. asks uv to make sure its tool-install directory is on PATH, then
#      confirms the command actually landed on PATH in this session
#
# ExaDoctor is read-only against your database and this installer never
# touches anything outside its own tool environment, so there is nothing
# to "uninstall carefully" -- `uv tool uninstall exadoctor` reverses this
# completely, and re-running this script is always safe.
#
# Options (environment variables, because piping through `iex` doesn't
# let you pass script parameters -- same reasoning as install.sh):
#   $env:EXADOCTOR_SOURCE   what `uv tool install` points at -- a git URL
#                           (default), a local path, or a PyPI name once
#                           published there
#   $env:EXADOCTOR_REF      git ref to install (tag/branch/commit); only
#                           applies when EXADOCTOR_SOURCE is left at its
#                           default git URL
#   $env:EXADOCTOR_DRY_RUN  set to "1" to print the plan and the resolved
#                           uv command, install nothing

$ErrorActionPreference = "Stop"

function Say  { param($msg) Write-Host "  * $msg" -ForegroundColor Blue }
function Ok   { param($msg) Write-Host "  + $msg" -ForegroundColor Green }
function Warn { param($msg) Write-Host "  ! $msg" -ForegroundColor Yellow }
function Fail { param($msg) Write-Host "  x $msg" -ForegroundColor Red; exit 1 }

function Main {
    # --- 1. preflight --------------------------------------------------------
    $exadoctorSourceDefault = "git+https://github.com/SanjayG-Data/ExaDoctor"
    $usingDefaultSource = -not $env:EXADOCTOR_SOURCE
    $exadoctorSource = if ($env:EXADOCTOR_SOURCE) { $env:EXADOCTOR_SOURCE } else { $exadoctorSourceDefault }

    if ($usingDefaultSource) {
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            Fail "git is required to install from the default source ($exadoctorSource). Install git, or set `$env:EXADOCTOR_SOURCE to a local path instead."
        }
        if ($env:EXADOCTOR_REF) {
            $exadoctorSource = "$exadoctorSource@$($env:EXADOCTOR_REF)"
        }
    } elseif ($env:EXADOCTOR_REF) {
        Warn "EXADOCTOR_REF is ignored because EXADOCTOR_SOURCE was set explicitly."
    }

    # --- 2. ensure uv ----------------------------------------------------------
    $uvBin = $null
    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvCmd) {
        $uvBin = $uvCmd.Source
    } elseif (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
        $uvBin = "$env:USERPROFILE\.local\bin\uv.exe"
    }

    if (-not $uvBin) {
        Say "Installing the Python tool manager (uv) -- one-time, ~10s"
        if ($env:EXADOCTOR_DRY_RUN -eq "1") {
            Say "(dry run: would run) irm https://astral.sh/uv/install.ps1 | iex"
        } else {
            try {
                Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
            } catch {
                Fail "Could not install uv. See https://docs.astral.sh/uv/getting-started/installation/ for manual install options."
            }
        }
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
        if ($uvCmd) {
            $uvBin = $uvCmd.Source
        } elseif (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
            $uvBin = "$env:USERPROFILE\.local\bin\uv.exe"
        } elseif ($env:EXADOCTOR_DRY_RUN -ne "1") {
            Fail "uv installation finished but the binary could not be found. Open a new PowerShell window and re-run this script."
        }
    } else {
        Ok "uv already installed ($uvBin)"
    }

    # --- 3. install exadoctor ---------------------------------------------------
    Say "Installing exadoctor from: $exadoctorSource"
    if ($env:EXADOCTOR_DRY_RUN -eq "1") {
        Say "(dry run: would run) uv tool install --force `"$exadoctorSource`""
        Say "Dry run requested (EXADOCTOR_DRY_RUN=1) -- nothing was installed."
        return
    }

    & $uvBin tool install --force $exadoctorSource
    if ($LASTEXITCODE -ne 0) {
        Fail "Could not install exadoctor. Check the error above -- a common cause is EXADOCTOR_REF pointing at a ref that doesn't exist."
    }

    # --- 4. confirm it's on PATH -------------------------------------------------
    # May append to this user's PATH (uv's own behavior for `tool install`
    # on Windows) if its tool-install directory isn't already on it.
    # Best-effort: a failure here doesn't undo the install above.
    try {
        & $uvBin tool update-shell 2>$null | Out-Null
    } catch {
        Warn "Could not update PATH automatically; see the note below if needed."
    }

    $exadoctorCmd = Get-Command exadoctor -ErrorAction SilentlyContinue
    if ($exadoctorCmd) {
        Ok "exadoctor installed: $($exadoctorCmd.Source)"
        Write-Host "`n  Next: exadoctor --help`n"
    } else {
        Warn "exadoctor was installed but is not on PATH in this session yet."
        Warn "Open a new PowerShell window, then run: exadoctor --help"
    }
}

Main
