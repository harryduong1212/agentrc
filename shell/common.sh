# Shared shell setup — sourced by both zsh and bash.
#
# Nothing here is machine-specific and nothing here is a secret. Both come from
# ~/.config/based/omniroute, which is NOT in this repo and never should be.
# That separation is what makes this repo safe to make public.

# ---------------------------------------------------------------- config read
# `key = value`, read with sed rather than sourced: this file is config, and
# config should not be able to execute anything. Same rule the workspace's own
# scripts/lib/server-host.sh follows.
_dot_config_file="${BASED_CONFIG_HOME:-$HOME/.config/based}/omniroute"

_dot_read() {
  [ -f "$_dot_config_file" ] || return 0
  sed -nE "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*(.*[^[:space:]])[[:space:]]*$/\1/p" \
    "$_dot_config_file" | head -1
}

# Env always wins, so a single command can override for one session without
# editing anything.
OMNIROUTE_URL="${OMNIROUTE_URL:-$(_dot_read url)}"
OMNIROUTE_API_KEY="${OMNIROUTE_API_KEY:-$(_dot_read key)}"
OMNIROUTE_COMBO="${OMNIROUTE_COMBO:-$(_dot_read combo)}"
OMNIROUTE_CODEX_COMBO="${OMNIROUTE_CODEX_COMBO:-$(_dot_read codex_combo)}"

# -------------------------------------------------------------- claude routing
# Deliberately no default URL. An empty ANTHROPIC_BASE_URL makes the CLI fall
# back to api.anthropic.com, which has never heard of a gateway model id — you
# get "model may not exist" on every request instead of a clear failure. Better
# to export nothing and have `claude` behave like a stock install.
if [ -n "$OMNIROUTE_URL" ] && [ -n "$OMNIROUTE_API_KEY" ]; then
  export ANTHROPIC_BASE_URL="$OMNIROUTE_URL"
  export ANTHROPIC_API_KEY="$OMNIROUTE_API_KEY"
  [ -n "$OMNIROUTE_COMBO" ] && export ANTHROPIC_DEFAULT_OPUS_MODEL="$OMNIROUTE_COMBO"
fi

# --------------------------------------------------------------- codex routing
# Codex reads its base_url from ~/.codex/config.toml and only the key from the
# environment, so this is the whole of its shell side.
[ -n "$OMNIROUTE_API_KEY" ] && export OMNIROUTE_API_KEY

unset _dot_config_file

# ------------------------------------------------------------------------ PATH
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) export PATH="$HOME/.local/bin:$PATH" ;;
esac

# --------------------------------------------------------------------- aliases
# The flags worth remembering, given names so you don't have to.
alias cc='claude'
alias ccc='claude --continue'
alias ccr='claude --resume'
alias cx='codex'
alias cxr='codex resume --last'
alias cxrr='codex resume'

# Where am I actually sending requests? The question you will ask most often.
omniroute-where() {
  echo "ANTHROPIC_BASE_URL = ${ANTHROPIC_BASE_URL:-<unset — going straight to Anthropic>}"
  echo "combo (claude)     = ${ANTHROPIC_DEFAULT_OPUS_MODEL:-<unset>}"
  echo "combo (codex)      = ${OMNIROUTE_CODEX_COMBO:-<unset>}"
  if [ -n "$ANTHROPIC_BASE_URL" ]; then
    printf 'gateway            = '
    curl -s -o /dev/null -w '%{http_code}\n' --max-time 5 \
      "$ANTHROPIC_BASE_URL/v1/models" 2>/dev/null || echo 'unreachable'
  fi
}
