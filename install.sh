#!/usr/bin/env bash
# Set up this machine from the repo. Safe to run twice — it reports what is
# already correct instead of redoing it.
#
#   ./install.sh              apply
#   ./install.sh --dry-run    print what would change, touch nothing
set -euo pipefail

DOTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${BASED_CONFIG_HOME:-$HOME/.config/based}"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

say()  { printf '  %s\n' "$*"; }
head_() { printf '\n%s\n' "$*"; }
run()  { if [ "$DRY" = 1 ]; then say "would: $*"; else "$@"; fi; }

# Symlink, but never over a real file you wrote yourself.
link() {
  local src="$1" dst="$2"
  if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
    say "ok       $dst"
  elif [ -e "$dst" ] && [ ! -L "$dst" ]; then
    say "SKIPPED  $dst already exists and is not a symlink — move it aside first"
  else
    run ln -sfn "$src" "$dst"
    if [ "$DRY" != 1 ]; then
      say "linked   $dst"
    fi
  fi
}

head_ "shell"
run mkdir -p "$HOME/.local/bin"
link "$DOTS/shell/common.sh" "$HOME/.based-shell.sh"
for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
  [ -f "$rc" ] || continue
  if grep -q '.based-shell.sh' "$rc" 2>/dev/null; then
    say "ok       $rc already sources it"
  else
    run sh -c "printf '\n# agentrc\n[ -f \"\$HOME/.based-shell.sh\" ] && . \"\$HOME/.based-shell.sh\"\n' >> '$rc'"
    if [ "$DRY" != 1 ]; then
      say "appended $rc"
    fi
  fi
done

head_ "commands"
for w in claude codex; do
  run chmod +x "$DOTS/bin/$w"
  link "$DOTS/bin/$w" "$HOME/.local/bin/$w"
done
if command -v pipx >/dev/null 2>&1; then
  if [ "$DRY" = 1 ]; then
    say "would: install or upgrade $DOTS/howto with pipx"
  else
    if pipx list --json 2>/dev/null | grep -q 'agentrc-howto'; then
      pipx install --force "$DOTS/howto"
      say "reinstalled howto with pipx"
    else
      pipx install "$DOTS/howto"
      say "installed howto with pipx"
    fi
  fi
  if [ "$DRY" = 1 ]; then
    say "would: link the pipx howto command into $HOME/.local/bin"
  else
    HOWTO_BIN_DIR="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || true)"
    HOWTO_CMD="${HOWTO_BIN_DIR:-$HOME/.local/bin}/howto"
    if [ "$HOWTO_CMD" = "$HOME/.local/bin/howto" ]; then
      say "ok       $HOME/.local/bin/howto installed by pipx"
    else
      link "$HOWTO_CMD" "$HOME/.local/bin/howto"
    fi
  fi
elif python3 -m venv --help >/dev/null 2>&1; then
  HOWTO_VENV="${XDG_DATA_HOME:-$HOME/.local/share}/agentrc/howto"
  HOWTO_PYTHON="$HOWTO_VENV/bin/python3"
  if [ ! -x "$HOWTO_VENV/bin/python3" ]; then
    run python3 -m venv "$HOWTO_VENV"
  fi
  run "$HOWTO_PYTHON" -m pip install --upgrade "$DOTS/howto"
  if [ "$DRY" = 1 ]; then
    say "would: install howto in $HOWTO_VENV"
  else
    say "installed howto in $HOWTO_VENV"
  fi
  link "$HOWTO_VENV/bin/howto" "$HOME/.local/bin/howto"
else
  say "using the repo-local howto wrapper — install pipx or Python's venv module for isolation"
  run chmod +x "$DOTS/bin/howto"
  link "$DOTS/bin/howto" "$HOME/.local/bin/howto"
fi

head_ "tmux, vim, git"
link "$DOTS/tmux/tmux.conf" "$HOME/.tmux.conf"
link "$DOTS/vim/vimrc" "$HOME/.vimrc"
run mkdir -p "$HOME/.vim/undo" "$HOME/.vim/backup" "$HOME/.vim/swap"
if grep -q 'defaultBranch' "$HOME/.gitconfig" 2>/dev/null; then
  say "ok       ~/.gitconfig already carries the snippet"
else
  run sh -c "cat '$DOTS/git/gitconfig.snippet' >> '$HOME/.gitconfig'"
  if [ "$DRY" != 1 ]; then
    say "appended ~/.gitconfig"
  fi
fi

head_ "machine config (never in the repo)"
run mkdir -p "$CONFIG_DIR"
if [ -f "$CONFIG_DIR/omniroute" ]; then
  say "ok       $CONFIG_DIR/omniroute exists"
else
  run cp "$DOTS/config-based/omniroute.template" "$CONFIG_DIR/omniroute"
  run chmod 600 "$CONFIG_DIR/omniroute"
  if [ "$DRY" = 1 ]; then
    say "would: create $CONFIG_DIR/omniroute — then fill it in"
  else
    say "created  $CONFIG_DIR/omniroute — FILL IT IN, it is empty"
  fi
fi

head_ "codex"
url="$(sed -nE 's/^[[:space:]]*url[[:space:]]*=[[:space:]]*(.*[^[:space:]])[[:space:]]*$/\1/p' "$CONFIG_DIR/omniroute" 2>/dev/null | head -1 || true)"
model="$(sed -nE 's/^[[:space:]]*codex_combo[[:space:]]*=[[:space:]]*(.*[^[:space:]])[[:space:]]*$/\1/p' "$CONFIG_DIR/omniroute" 2>/dev/null | head -1 || true)"
if [ -z "$url" ]; then
  say "SKIPPED  ~/.codex/config.toml — no url in $CONFIG_DIR/omniroute yet"
else
  run mkdir -p "$HOME/.codex"
  if [ "$DRY" = 1 ]; then
    say "would: build ~/.codex/model-catalog.json with the OmniRoute Codex pools"
    say "would: write ~/.codex/config.toml pointing at $url"
  else
    "$DOTS/codex/build-model-catalog.py" \
      --codex "$DOTS/bin/codex" --output "$HOME/.codex/model-catalog.json"
    sed -e "s|__BASE_URL__|$url|" -e "s|__MODEL__|${model:-auto/best-coding}|" \
      -e "s|__MODEL_CATALOG__|$HOME/.codex/model-catalog.json|" \
      "$DOTS/codex/config.toml.template" > "$HOME/.codex/config.toml"
    say "wrote    ~/.codex/model-catalog.json"
    say "wrote    ~/.codex/config.toml"
  fi
fi

head_ "done"
say "open a new shell, then run: omniroute-where"
