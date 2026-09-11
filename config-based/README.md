# `~/.config/based/` — the files that are never in a repo

Everything machine-specific lives in `${BASED_CONFIG_HOME:-~/.config/based}/`,
outside git. That separation is the whole reason this repo can be public: the
tracked side carries the **shape** of each file, the untracked side carries your
values.

`../install.sh` creates `omniroute` for you. The rest are copies:

```bash
mkdir -p ~/.config/based
cp config-based/server.template              ~/.config/based/server
cp config-based/mcp-profile.template         ~/.config/based/mcp-profile
cp config-based/shareable-deny.txt.template  ~/.config/based/shareable-deny.txt
# routing metadata is easier to generate than to write:
./omniroute/apply-routing.sh --seed
```

| File | Read by | Format |
|---|---|---|
| `omniroute` | `shell/common.sh`, `install.sh`, `omniroute/switch-combo.sh` | `key = value`. Holds the gateway URL, its API key and the combo names. **The only file here that holds a secret** — `chmod 600`, never copied back into a repo |
| `omniroute-routing.json` | `omniroute/apply-routing.sh` | JSON; keys starting `_` are ignored. Prefer `--seed`, which writes your live gateway state, over filling it in by hand |
| `server` | a private workspace repo's `scripts/lib/server-host.sh` | `key = value`, last one wins. `BASED_SERVER_HOST` / `BASED_SERVER_IP` in the environment beat the file |
| `mcp-profile` | a private workspace repo's `scripts/mcp-profile.sh` | **Exactly one word.** The reader is `cat`, so a comment line breaks it — that is why that template has none |
| `shareable-deny.txt` | a private workspace repo's `scripts/lint_shareable.py` | One token per line, `#` comments, `word:` prefix for a whole-word match. The per-machine half of a deny list whose other half is tracked |

The last three are read by a repo that is not this one. They live here anyway
so that setting up a machine is one checkout and one pass, not two.

Two rules hold for every file in this directory:

- **No reader may source or execute it.** `sed`, `cat` and `JSON.parse` only. A
  config file that can run commands is not config.
- **No defaults for identity.** A hostname or key that falls back to something
  plausible fails silently on the wrong machine. Empty, then a clear error.

If you add a file here, add its template in the same commit — otherwise the next
machine gets set up by reading script source.
