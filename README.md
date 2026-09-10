# agentrc

My terminal setup: two coding agents behind one LLM gateway, plus the shell,
tmux, vim and git config that goes with them. Linux only — a Fedora laptop and
a WSL box, and whatever machine comes next.

```bash
git clone https://github.com/harryduong1212/agentrc.git ~/agentrc
cd ~/agentrc
./install.sh --dry-run   # see what it would do
./install.sh
```

Then fill in `~/.config/based/omniroute` and open a new shell.

## Why nothing here is secret

This repo is public. Every secret and every machine name lives in one file the
repo does not contain:

```
~/.config/based/omniroute      mode 0600, never committed
```

`shell/common.sh` reads it with `sed` rather than sourcing it, so a config file
can never execute anything. `install.sh` creates it from
`config-based/omniroute.template` and leaves it empty for you to fill in.

If you ever find yourself typing a key, a hostname or a domain into a tracked
file here, that is the bug.

## What is in it

| Path | Goes to | What it does |
|---|---|---|
| `shell/common.sh` | `~/.based-shell.sh` | Points both agents at the gateway; adds aliases and `omniroute-where` |
| `bin/claude`, `bin/codex` | `~/.local/bin/` | Makes both agents one word. Finds the real binary inside the VS Code extension at run time, so an extension update cannot break them |
| `codex/config.toml.template` | `~/.codex/config.toml` | Codex's gateway provider. `install.sh` fills in the URL |
| `tmux/tmux.conf` | `~/.tmux.conf` | Mouse on, `Ctrl-a` prefix, no plugins |
| `vim/vimrc` | `~/.vimrc` | A first vimrc, short enough to read in full |
| `git/gitconfig.snippet` | appended to `~/.gitconfig` | Defaults and a few aliases. No identity — set that per machine |

## The one thing to understand

The two agents speak different protocols. The gateway answers both, so one
gateway serves both, and both bill to the same place:

```
claude  ──/v1/messages─────────┐
                               ├──▶  your gateway  ──▶  upstream providers
codex   ──/v1/chat/completions─┘
```

`claude` reads its address from the environment. `codex` reads its address from
`~/.codex/config.toml` and only its key from the environment. That asymmetry is
why there are two config surfaces and not one.

Check where you are actually sending requests:

```bash
omniroute-where
```

A blank `ANTHROPIC_BASE_URL` means the shell never loaded the config, and your
requests are going straight to the vendor rather than through the gateway.

## Everyday commands

```bash
claude              # new conversation      codex
claude --continue   # resume the last one   codex resume --last
claude --resume     # pick from a list      codex resume
```

Aliases for the same: `cc`, `ccc`, `ccr` and `cx`, `cxr`, `cxrr`.

## tmux

Start or rejoin a session that survives a dropped SSH connection:

```bash
tmux new -A -s work
```

`Ctrl-a` then `d` detaches and leaves everything running. `Ctrl-a` then `|` and
`-` split. The mouse works. `Ctrl-a` then `r` reloads the config.

## Not in here

Anything for Windows. WSL is Linux and takes these files directly; the Windows
side needs only an SSH client and a terminal, which are not dotfiles.
