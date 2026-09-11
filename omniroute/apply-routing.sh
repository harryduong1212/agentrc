#!/usr/bin/env bash
# Reconcile OmniRoute's routing metadata (bare-name aliases + pattern→combo
# mapping rules) against a declarative config file. The script is generic —
# every model id, combo name and pattern lives in the config, never here.
#
# Config file (JSON, untracked, yours to edit):
#   ${OMNIROUTE_ROUTING_CONFIG:-${BASED_CONFIG_HOME:-~/.config/based}/omniroute-routing.json}
# Schema: see ../config-based/omniroute-routing.json.template.
#
# Target grammar (the right-hand side of an alias):
#   "my-combo"            bare name         → must be an existing combo
#   "combo/my-combo"      explicit combo    → must be an existing combo
#   "provider/model-id"   provider pin      → passed through unvalidated
# A mapping rule's "combo" is always a combo name, resolved to its UUID live —
# never store the UUID (setup-smart-routing.sh hardcoded one; this fixes that).
#
# Usage
#   ./apply-routing.sh --seed        # write the LIVE gateway state into the
#                                    # config file (refuses to overwrite)
#   ./apply-routing.sh --dry-run     # diff config against the gateway
#   ./apply-routing.sh               # apply the diff
#   ./apply-routing.sh --prune       # apply, and delete rows not in config
#   ./apply-routing.sh --show        # read-only dump: combos, aliases, rules
#   ./apply-routing.sh --probe <id>  # after apply: send one 4-token request
#                                    # for <id> and print what actually served it
#
# Why sqlite and not the management API: /api/models/alias answers 403 to an
# inference key since 2026-09-08 (see sync-aliases.sh header). Writes go
# straight to the container's storage.sqlite, the way setup-smart-routing.sh
# already does; rows are picked up live, no restart.
#
# Family guard: an alias or pattern routed to a combo whose members serve a
# different model family comes back HTTP 200 with the wrong model — the
# 2026-07-04 Fable incident and the 2026-07-31 Sonnet/Haiku repeat. The diff
# WARNS on every such entry instead of erroring, because the live setup
# deliberately pools some near-family ids; read each warning and decide.
set -euo pipefail

CONFIG_DIR="${BASED_CONFIG_HOME:-$HOME/.config/based}"
CONFIG="${OMNIROUTE_ROUTING_CONFIG:-$CONFIG_DIR/omniroute-routing.json}"

MODE="apply" PRUNE=false PROBE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --show)    MODE="show";  shift ;;
    --seed)    MODE="seed";  shift ;;
    --dry-run) MODE="plan";  shift ;;
    --prune)   PRUNE=true;   shift ;;
    --probe)   PROBE="$2";   shift 2 ;;
    --config)  CONFIG="$2";  shift 2 ;;
    -h|--help) sed -n '2,33p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 3 ;;
  esac
done

# Container engine and container name are discovered, not hardcoded.
ENGINE="${OMNIROUTE_ENGINE:-}"
if [[ -z "$ENGINE" ]]; then
  command -v podman >/dev/null && ENGINE=podman || ENGINE=docker
  command -v "$ENGINE" >/dev/null || { echo "error: neither podman nor docker on PATH" >&2; exit 3; }
fi
CONTAINER="${OMNIROUTE_CONTAINER:-}"
if [[ -z "$CONTAINER" ]]; then
  mapfile -t hits < <("$ENGINE" ps --format '{{.Names}}' --filter name=omniroute)
  if [[ ${#hits[@]} -ne 1 ]]; then
    echo "error: expected exactly one running *omniroute* container, found ${#hits[@]}:" >&2
    printf '  %s\n' "${hits[@]:-<none>}" >&2
    echo "set OMNIROUTE_CONTAINER to pick one" >&2
    exit 3
  fi
  CONTAINER="${hits[0]}"
fi

NODE_SRC=$(cat <<'EOF'
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const { mode, prune } = input.opts;
const db = require('better-sqlite3')('/app/data/storage.sqlite',
  { readonly: mode !== 'apply' });

// --- live state ---------------------------------------------------------
const combos = {};                       // name -> {id, leaves:[bare ids]}
const comboRows = db.prepare('SELECT id,name,data FROM combos').all();
for (const c of comboRows) combos[c.name] = { id: c.id, data: JSON.parse(c.data || '{}') };
function leaves(name, seen = new Set()) {
  if (seen.has(name) || !combos[name]) return [];
  seen.add(name);
  const out = [];
  for (const m of combos[name].data.models || []) {
    if (m.kind === 'combo-ref') out.push(...leaves(m.comboName, seen));
    else if (m.model) out.push(m.model.split('/').pop());
  }
  return out;
}
const aliasRows = db.prepare(
  "SELECT key,value FROM key_value WHERE namespace='modelAliases'").all();
const curAliases = {};
for (const r of aliasRows) { try { curAliases[r.key] = JSON.parse(r.value); } catch { curAliases[r.key] = r.value; } }
const mapRows = db.prepare(
  'SELECT id,pattern,combo_id,priority,enabled FROM model_combo_mappings').all();
const comboById = Object.fromEntries(comboRows.map(c => [c.id, c.name]));

// family stem: "claude-opus-4-7" -> "claude-opus"; "claude-opus-*" -> "claude-opus"
const family = s => String(s).toLowerCase().split('/').pop()
  .replace(/\*.*$/, '').replace(/[-._]?\d.*$/, '').replace(/[-._]+$/, '');

if (mode === 'show') {
  console.log('combos:');
  for (const c of comboRows) {
    const d = combos[c.name].data;
    console.log(`  ${c.name}  strategy=${d.strategy}  active=${d.isActive !== false}`);
    for (const m of d.models || [])
      console.log(m.kind === 'combo-ref'
        ? `    -> combo ${m.comboName}`
        : `    -> ${m.model}${m.label ? '  (' + m.label + ')' : ''}`);
  }
  console.log(`aliases (${aliasRows.length}):`);
  for (const r of [...aliasRows].sort((a, b) => a.key.localeCompare(b.key)))
    console.log(`  ${r.key.padEnd(34)} -> ${curAliases[r.key]}`);
  console.log(`mapping rules (${mapRows.length}):`);
  for (const r of mapRows)
    console.log(`  ${r.pattern.padEnd(34)} -> ${comboById[r.combo_id] || 'MISSING combo ' + r.combo_id}  priority=${r.priority}  enabled=${r.enabled}`);
  process.exit(0);
}

if (mode === 'seed') {
  const aliases = {};
  for (const k of Object.keys(curAliases).sort()) aliases[k] = curAliases[k];
  const mappings = mapRows.filter(r => r.enabled).map(r => ({
    pattern: r.pattern, combo: comboById[r.combo_id] || r.combo_id, priority: r.priority }));
  console.log(JSON.stringify({ aliases, mappings }, null, 2));
  process.exit(0);
}

// --- plan / apply -------------------------------------------------------
const cfg = input.config;
if (!cfg || typeof cfg !== 'object') { console.error('✗ config is not a JSON object'); process.exit(2); }
const wantAliases = cfg.aliases || {};
const wantMappings = cfg.mappings || [];
const errors = [], warns = [];

// resolve + validate an alias target; returns null for provider pins
function comboOf(target) {
  const t = String(target);
  if (!t.includes('/')) return combos[t] ? t : (errors.push(`alias target "${t}" is not a known combo`), undefined);
  const [pfx, ...rest] = t.split('/');
  if (pfx !== 'combo') return null;                       // provider pin, unvalidated
  const name = rest.join('/');
  return combos[name] ? name : (errors.push(`alias target "${t}" names no known combo`), undefined);
}
for (const [k, v] of Object.entries(wantAliases)) {
  if (typeof v !== 'string' || !v) { errors.push(`alias "${k}" has a non-string target`); continue; }
  const cn = comboOf(v);
  if (cn && !leaves(cn).some(l => family(l) === family(k)))
    warns.push(`alias ${k} -> combo ${cn}: no member serves family "${family(k)}" (members: ${[...new Set(leaves(cn))].join(', ') || 'none'})`);
}
const wantRules = {};
for (const m of wantMappings) {
  if (!m.pattern || !m.combo) { errors.push(`mapping ${JSON.stringify(m)} needs pattern and combo`); continue; }
  if (!combos[m.combo]) { errors.push(`mapping "${m.pattern}": combo "${m.combo}" does not exist`); continue; }
  if (!leaves(m.combo).some(l => family(l) === family(m.pattern)))
    warns.push(`mapping ${m.pattern} -> ${m.combo}: no member serves family "${family(m.pattern)}"`);
  wantRules[m.pattern] = { combo_id: combos[m.combo].id, priority: m.priority ?? 100, combo: m.combo };
}
for (const w of warns) console.log(`! ${w}`);
if (errors.length) { for (const e of errors) console.error(`✗ ${e}`); process.exit(2); }

const acts = [];  // {line, run}
for (const [k, v] of Object.entries(wantAliases)) {
  if (!(k in curAliases)) acts.push({ line: `+ alias   ${k} -> ${v}`, run: () =>
    db.prepare('INSERT INTO key_value (namespace,key,value) VALUES (?,?,?)').run('modelAliases', k, JSON.stringify(v)) });
  else if (curAliases[k] !== v) acts.push({ line: `~ alias   ${k}: ${curAliases[k]} -> ${v}`, run: () =>
    db.prepare("UPDATE key_value SET value=? WHERE namespace='modelAliases' AND key=?").run(JSON.stringify(v), k) });
}
for (const k of Object.keys(curAliases)) if (!(k in wantAliases))
  acts.push({ line: `${prune ? '-' : '?'} alias   ${k} -> ${curAliases[k]}  (${prune ? 'delete' : 'not in config — kept; --prune deletes'})`,
    run: prune ? () => db.prepare("DELETE FROM key_value WHERE namespace='modelAliases' AND key=?").run(k) : null });
const now = new Date().toISOString();
for (const [p, w] of Object.entries(wantRules)) {
  const cur = mapRows.find(r => r.pattern === p);
  if (!cur) acts.push({ line: `+ mapping ${p} -> ${w.combo}`, run: () =>
    db.prepare('INSERT INTO model_combo_mappings (id,pattern,combo_id,priority,enabled,description,created_at,updated_at) VALUES (?,?,?,?,1,?,?,?)')
      .run(require('crypto').randomUUID(), p, w.combo_id, w.priority, `Route ${p} to ${w.combo}`, now, now) });
  else if (cur.combo_id !== w.combo_id || cur.priority !== w.priority || !cur.enabled)
    acts.push({ line: `~ mapping ${p} -> ${w.combo}  (was ${comboById[cur.combo_id] || cur.combo_id}, priority=${cur.priority}, enabled=${cur.enabled})`, run: () =>
      db.prepare('UPDATE model_combo_mappings SET combo_id=?, priority=?, enabled=1, updated_at=? WHERE pattern=?').run(w.combo_id, w.priority, now, p) });
}
for (const r of mapRows) if (!(r.pattern in wantRules))
  acts.push({ line: `${prune ? '-' : '?'} mapping ${r.pattern} -> ${comboById[r.combo_id] || r.combo_id}  (${prune ? 'delete' : 'not in config — kept; --prune deletes'})`,
    run: prune ? () => db.prepare('DELETE FROM model_combo_mappings WHERE pattern=?').run(r.pattern) : null });

const doable = acts.filter(a => a.run);
for (const a of acts) console.log(a.line);
if (!doable.length) { console.log(`no changes — gateway matches config (${Object.keys(wantAliases).length} aliases, ${Object.keys(wantRules).length} rules)`); process.exit(0); }
if (mode === 'plan') { console.log(`plan: ${doable.length} change(s), nothing written (--dry-run)`); process.exit(0); }
db.transaction(() => { for (const a of doable) a.run(); })();
console.log(`applied ${doable.length} change(s)`);
EOF
)

run_node() {
  printf '%s' "$1" | "$ENGINE" exec -i "$CONTAINER" node -e "$NODE_SRC"
}

case "$MODE" in
  show) run_node '{"opts":{"mode":"show","prune":false},"config":null}' ;;
  seed)
    if [[ -e "$CONFIG" ]]; then
      echo "error: $CONFIG already exists — edit it, or move it away to re-seed" >&2; exit 3
    fi
    mkdir -p "$(dirname "$CONFIG")"
    ( umask 077; run_node '{"opts":{"mode":"seed","prune":false},"config":null}' > "$CONFIG" )
    echo "seeded $CONFIG from the live gateway ($(wc -l < "$CONFIG") lines)"
    echo "next: ./apply-routing.sh --dry-run should report no changes"
    ;;
  plan|apply)
    [[ -f "$CONFIG" ]] || { echo "error: no config at $CONFIG — run --seed first, or see config-based/omniroute-routing.json.template" >&2; exit 3; }
    run_node "{\"opts\":{\"mode\":\"$MODE\",\"prune\":$PRUNE},\"config\":$(cat "$CONFIG")}"
    ;;
esac

if [[ -n "$PROBE" && "$MODE" == "apply" ]]; then
  # Same `url =` the shell and codex read — sed, never sourced.
  BASE="${OMNIROUTE_BASE:-$(sed -nE 's/^[[:space:]]*url[[:space:]]*=[[:space:]]*(.*[^[:space:]])[[:space:]]*$/\1/p' \
    "$CONFIG_DIR/omniroute" 2>/dev/null | head -1 || true)}"
  [[ -n "$BASE" ]] || { echo "probe skipped: no url in $CONFIG_DIR/omniroute, and OMNIROUTE_BASE unset" >&2; exit 0; }
  hdrs="$(mktemp)"
  code=$(curl -sS -o /dev/null -D "$hdrs" -w '%{http_code}' --max-time 60 \
    -X POST "$BASE/v1/messages" \
    -H "content-type: application/json" -H "anthropic-version: 2023-06-01" \
    -d "{\"model\":\"$PROBE\",\"max_tokens\":4,\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}]}" || true)
  echo "probe $PROBE: HTTP $code  $(grep -i '^x-omniroute-model\|^x-omniroute-provider\|^x-omniroute-decision' "$hdrs" | tr -d '\r' | paste -sd '  ' -)"
  rm -f "$hdrs"
fi
