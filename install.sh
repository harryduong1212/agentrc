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
    say "linked   $dst"
  fi
}

head_ "shell"
mkdir -p "$HOME/.local/bin"
link "$DOTS/shell/common.sh" "$HOME/.based-shell.sh"
for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
  [ -f "$rc" ] || continue
  if grep -q '.based-shell.sh' "$rc" 2>/dev/null; then
    say "ok       $rc already sources it"
  else
    run sh -c "printf '\n# agentrc\n[ -f \"\$HOME/.based-shell.sh\" ] && . \"\$HOME/.based-shell.sh\"\n' >> '$rc'"
    say "appended $rc"
  fi
done

head_ "agent wrappers"
for w in claude codex; do
  run chmod +x "$DOTS/bin/$w"
  link "$DOTS/bin/$w" "$HOME/.local/bin/$w"
done

head_ "tmux, vim, git"
link "$DOTS/tmux/tmux.conf" "$HOME/.tmux.conf"
link "$DOTS/vim/vimrc" "$HOME/.vimrc"
run mkdir -p "$HOME/.vim/undo" "$HOME/.vim/backup" "$HOME/.vim/swap"
if grep -q 'defaultBranch' "$HOME/.gitconfig" 2>/dev/null; then
  say "ok       ~/.gitconfig already carries the snippet"
else
  run sh -c "cat '$DOTS/git/gitconfig.snippet' >> '$HOME/.gitconfig'"
  say "appended ~/.gitconfig"
fi

head_ "machine config (never in the repo)"
run mkdir -p "$CONFIG_DIR"
if [ -f "$CONFIG_DIR/omniroute" ]; then
  say "ok       $CONFIG_DIR/omniroute exists"
else
  run cp "$DOTS/config-based/omniroute.template" "$CONFIG_DIR/omniroute"
  run chmod 600 "$CONFIG_DIR/omniroute"
  say "created  $CONFIG_DIR/omniroute — FILL IT IN, it is empty"
fi

head_ "codex"
url="$(sed -nE 's/^[[:space:]]*url[[:space:]]*=[[:space:]]*(.*[^[:space:]])[[:space:]]*$/\1/p' "$CONFIG_DIR/omniroute" 2>/dev/null | head -1 || true)"
model="$(sed -nE 's/^[[:space:]]*codex_combo[[:space:]]*=[[:space:]]*(.*[^[:space:]])[[:space:]]*$/\1/p' "$CONFIG_DIR/omniroute" 2>/dev/null | head -1 || true)"
if [ -z "$url" ]; then
  say "SKIPPED  ~/.codex/config.toml — no url in $CONFIG_DIR/omniroute yet"
else
  run mkdir -p "$HOME/.codex"
  if [ "$DRY" = 1 ]; then
    say "would: write ~/.codex/config.toml pointing at $url"
  else
    sed -e "s|__BASE_URL__|$url|" -e "s|__MODEL__|${model:-auto/best-coding}|" \
      "$DOTS/codex/config.toml.template" > "$HOME/.codex/config.toml"
    say "wrote    ~/.codex/config.toml"
  fi
fi

head_ "done"
say "open a new shell, then run: omniroute-where"
