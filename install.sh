#!/bin/sh
# install.sh -- ExaDoctor one-command installer.
#
#   curl -fsSL https://raw.githubusercontent.com/SanjayG-Data/ExaDoctor/main/install.sh | sh
#
# What it does, in order:
#   1. checks for curl and git (needed to fetch uv and the source)
#   2. installs uv if it isn't already on this machine, via the official
#      Astral installer (https://docs.astral.sh/uv/) -- uv is a real,
#      persistent prerequisite (ExaDoctor is a Python + pyexasol tool, not
#      a shell script), so this step makes it invisible rather than
#      pretending it isn't needed
#   3. runs `uv tool install` against the ExaDoctor source, which resolves
#      pyexasol/click into an isolated environment and installs a
#      standalone `exadoctor` command -- no `uv run`, no venv activation,
#      no uv at all needed to use it afterward
#   4. asks uv to make sure its tool-install directory is on PATH (this can
#      append a line to your shell profile, e.g. ~/.bashrc/~/.zshrc -- the
#      same thing `uv tool update-shell` always does, on request here
#      rather than silently), then confirms the command actually landed
#      on PATH
#
# ExaDoctor is read-only against your database and this installer never
# touches anything outside its own tool environment, so there is nothing
# to "uninstall carefully" -- `uv tool uninstall exadoctor` reverses this
# completely, and re-running this script is always safe.
#
# Options (environment variables, because flags don't survive a pipe):
#   EXADOCTOR_SOURCE=...   what `uv tool install` points at -- a git URL
#                          (default), a local path, or a PyPI name once
#                          published there
#   EXADOCTOR_REF=...      git ref to install (tag/branch/commit); only
#                          applies when EXADOCTOR_SOURCE is left at its
#                          default git URL
#   EXADOCTOR_DRY_RUN=1    print the plan and the resolved uv command,
#                          install nothing
#
# Windows (PowerShell): this script needs `sh`, which native PowerShell
# doesn't have -- use install.ps1 instead:
#   irm https://raw.githubusercontent.com/SanjayG-Data/ExaDoctor/main/install.ps1 | iex
# (Git Bash/WSL users can still run this script as-is.)

set -u

EXADOCTOR_SOURCE_DEFAULT="git+https://github.com/SanjayG-Data/ExaDoctor"

main() {
    # Plain ASCII, no color, when stdout isn't a terminal (e.g. redirected
    # to a log file) -- avoids raw \033[...m escapes cluttering a log.
    if [ -t 1 ]; then
        say()  { printf '  \033[1;34m*\033[0m %s\n' "$*"; }
        ok()   { printf '  \033[1;32m+\033[0m %s\n' "$*"; }
        warn() { printf '  \033[1;33m!\033[0m %s\n' "$*" >&2; }
        fail() { printf '\033[1;31m  x\033[0m %s\n' "$*" >&2; exit 1; }
    else
        say()  { printf '  * %s\n' "$*"; }
        ok()   { printf '  + %s\n' "$*"; }
        warn() { printf '  ! %s\n' "$*" >&2; }
        fail() { printf '  x %s\n' "$*" >&2; exit 1; }
    fi

    # --- 1. preflight ------------------------------------------------------
    command -v curl >/dev/null 2>&1 || fail "curl is required."
    [ -n "${HOME:-}" ] || fail "\$HOME is not set; cannot determine where uv installs its binaries."

    using_default_source=1
    exadoctor_source="${EXADOCTOR_SOURCE:-$EXADOCTOR_SOURCE_DEFAULT}"
    [ "${EXADOCTOR_SOURCE:-}" = "" ] || using_default_source=0

    if [ "$using_default_source" = "1" ]; then
        command -v git >/dev/null 2>&1 \
            || fail "git is required to install from the default source ($exadoctor_source). Install git, or set EXADOCTOR_SOURCE to a local path instead."
        if [ -n "${EXADOCTOR_REF:-}" ]; then
            exadoctor_source="${exadoctor_source}@${EXADOCTOR_REF}"
        fi
    elif [ -n "${EXADOCTOR_REF:-}" ]; then
        warn "EXADOCTOR_REF is ignored because EXADOCTOR_SOURCE was set explicitly."
    fi

    # --- 2. ensure uv --------------------------------------------------------
    uv_bin=""
    if command -v uv >/dev/null 2>&1; then
        uv_bin="$(command -v uv)"
    elif [ -x "$HOME/.local/bin/uv" ]; then
        uv_bin="$HOME/.local/bin/uv"
    fi

    if [ -z "$uv_bin" ]; then
        say "Installing the Python tool manager (uv) -- one-time, ~10s"
        if [ "${EXADOCTOR_DRY_RUN:-0}" = "1" ]; then
            say "(dry run: would run) curl -LsSf https://astral.sh/uv/install.sh | sh"
        else
            curl -LsSf https://astral.sh/uv/install.sh | sh \
                || fail "Could not install uv. See https://docs.astral.sh/uv/getting-started/installation/ for manual install options."
        fi
        if command -v uv >/dev/null 2>&1; then
            uv_bin="$(command -v uv)"
        elif [ -x "$HOME/.local/bin/uv" ]; then
            uv_bin="$HOME/.local/bin/uv"
        elif [ "${EXADOCTOR_DRY_RUN:-0}" != "1" ]; then
            fail "uv installation finished but the binary could not be found. Open a new shell and re-run this script."
        fi
    else
        ok "uv already installed ($uv_bin)"
    fi

    # --- 3. install exadoctor ------------------------------------------------
    say "Installing exadoctor from: $exadoctor_source"
    if [ "${EXADOCTOR_DRY_RUN:-0}" = "1" ]; then
        say "(dry run: would run) uv tool install --force \"$exadoctor_source\""
        say "Dry run requested (EXADOCTOR_DRY_RUN=1) -- nothing was installed."
        exit 0
    fi

    "$uv_bin" tool install --force "$exadoctor_source" \
        || fail "Could not install exadoctor. Check the error above -- a common cause is EXADOCTOR_REF pointing at a ref that doesn't exist."

    # --- 4. confirm it's on PATH ---------------------------------------------
    # May append a PATH line to your shell profile (e.g. ~/.bashrc,
    # ~/.zshrc) if uv's tool-install directory isn't already on it -- this
    # is uv's own behavior, invoked here explicitly rather than left to
    # chance. Best-effort: a failure here doesn't undo the install above.
    if "$uv_bin" tool update-shell 2>/dev/null; then
        :
    else
        warn "Could not update your shell profile automatically; see the PATH note below if needed."
    fi

    if command -v exadoctor >/dev/null 2>&1; then
        ok "exadoctor installed: $(command -v exadoctor)"
        printf '\n  Next: exadoctor --help\n\n'
    else
        warn "exadoctor was installed but is not on PATH in this shell yet."
        warn "Open a new terminal (or re-source your shell profile), then run: exadoctor --help"
    fi
}

main "$@"
