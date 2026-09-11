#!/usr/bin/env bash
# Point the agents at a different combo, on every surface at once.
#
# A combo id lives in more than one place, and they must move together or half
# the stack keeps asking for the old one:
#   ~/.config/based/omniroute     combo = / codex_combo =   (the shell reads it)
#   VS Code settings.json         ANTHROPIC_DEFAULT_*       (the extension)
#   ~/.codex/config.toml          model =                   (codex)
#
# Usage
#   ./switch-combo.sh --to <combo>            # the combo claude asks for
#   ./switch-combo.sh --codex --to <combo>    # the combo codex asks for
#   ./switch-combo.sh --to <combo> --dry-run
#   ./switch-combo.sh --from <old> --to <combo>
#
# --from is only needed when the current value cannot be read from
# ~/.config/based/omniroute. Idempotent: one .bak-<timestamp> per file per run,
# and no backup at all when nothing changed.
#
# The combo must already exist in the gateway — combos are made in its web UI,
# and a request for a name it does not know comes back 400.
set -euo pipefail

CONFIG_DIR="${BASED_CONFIG_HOME:-$HOME/.config/based}"
CONFIG="$CONFIG_DIR/omniroute"
CODEX_TOML="$HOME/.codex/config.toml"

# VS Code keeps settings in a different place per install shape. Machine wins
# over User: on WSL that is the file the extension actually reads.
SETTINGS_CANDIDATES=(
  "$HOME/.vscode-server/data/Machine/settings.json"
  "$HOME/.vscode-server/data/User/settings.json"
  "$HOME/.config/Code/User/settings.json"
  "$HOME/.vscode/data/User/settings.json"
)

# The env slots whose value IS the combo id. Add one here and the rest follows.
KEYS=(
  ANTHROPIC_DEFAULT_OPUS_MODEL
  ANTHROPIC_DEFAULT_SONNET_MODEL
  ANTHROPIC_DEFAULT_HAIKU_MODEL
)

from="" to="" dry_run=0 codex=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from)  from="$2"; shift 2 ;;
    --to)    to="$2";   shift 2 ;;
    --codex) codex=1;   shift ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$to" ]] || { echo "error: --to <combo> is required" >&2; exit 2; }

key_name="combo"; [[ "$codex" == 1 ]] && key_name="codex_combo"

# `key = value`, read with sed rather than sourced — config does not execute.
read_key() {
  sed -nE "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*(.*[^[:space:]])[[:space:]]*$/\1/p" \
    "$CONFIG" 2>/dev/null | head -1
}

if [[ -z "$from" ]]; then
  # `|| true`: a missing config file makes sed exit non-zero, and under `set -e`
  # that kills the script here — before the error below can say why.
  from="$(read_key "$key_name" || true)"
  [[ -n "$from" ]] || { echo "error: $key_name is empty in $CONFIG — pass --from" >&2; exit 2; }
fi

if [[ "$from" == "$to" ]]; then
  echo "nothing to do: $key_name is already '$to'"
  exit 0
fi

ts=$(date +%Y%m%d-%H%M%S)
echo "→ $key_name:  $from  →  $to"
[[ "$dry_run" == 1 ]] && echo "  (dry-run: nothing is written)"

# Replace in place, keeping a backup, unless this is a dry run.
edit() {                       # edit <file> <sed-expr...>
  local f="$1"; shift
  if [[ "$dry_run" == 0 ]]; then
    cp "$f" "$f.bak-$ts"
    sed -i "$@" "$f"
  fi
}

# --- ~/.config/based/omniroute -------------------------------------------------
if [[ -f "$CONFIG" ]]; then
  edit "$CONFIG" -E "s|^([[:space:]]*$key_name[[:space:]]*=[[:space:]]*).*$|\1$to|"
  echo "  ✓ $CONFIG"
else
  echo "  · $CONFIG not found — skipped (run install.sh first)"
fi

# --- VS Code settings.json -----------------------------------------------------
# A line-scoped sed, not jq: this file is JSONC — it carries comments, and jq
# refuses to parse it. Matching the key means unrelated strings equal to $from
# are never touched.
if [[ "$codex" == 1 ]]; then
  : # codex takes no part in the VS Code env
else
  found=0
  for s in "${SETTINGS_CANDIDATES[@]}"; do
    [[ -f "$s" ]] || continue
    found=1
    hits=0
    for k in "${KEYS[@]}"; do
      grep -qE "\"$k\"[[:space:]]*:[[:space:]]*\"$from\"" "$s" && hits=1
    done
    if [[ "$hits" == 1 ]]; then
      args=()
      for k in "${KEYS[@]}"; do
        args+=(-e "s|(\"$k\"[[:space:]]*:[[:space:]]*\")$from(\")|\1$to\2|")
      done
      edit "$s" -E "${args[@]}"
      echo "  ✓ $s"
    else
      echo "  · $s already off '$from' — skipped"
    fi
  done
  [[ "$found" == 1 ]] || echo "  · no VS Code settings.json found — skipped"
fi

# --- ~/.codex/config.toml ------------------------------------------------------
if [[ "$codex" == 1 ]]; then
  if [[ -f "$CODEX_TOML" ]]; then
    edit "$CODEX_TOML" -E "s|^([[:space:]]*model[[:space:]]*=[[:space:]]*\").*(\")|\1$to\2|"
    echo "  ✓ $CODEX_TOML"
  else
    echo "  · $CODEX_TOML not found — skipped (run install.sh first)"
  fi
fi

cat <<EOF

next:
  open a new shell (or re-source ~/.based-shell.sh), then: omniroute-where
EOF
