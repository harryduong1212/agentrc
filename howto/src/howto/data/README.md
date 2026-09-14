# `howto/data/*` — the content

One file per **(tool, view)** pair. A tool is a stem; `tmux.keys` and
`tmux.help` are its two views, and either may be absent. The package reads every
`*.keys` and `*.help` here, sorts favourites first and then alphabetically, and
never needs touching to add a tool.

The two views are never merged, because they have different sources of truth:

| view | answers | read from |
|---|---|---|
| `*.keys` | what to press **inside** a tool | that tool's own live config |
| `*.help` | what to type **at the shell** | that tool's `--help` |

`tmux --help` prints one usage line while `tmux list-keys` prints 266 bindings;
`git --help` prints 4 flags while `git help -a` prints 178 subcommands. One pane
holding both would have no way to say which half you were looking at.

## The format

```
name:    tmux
what:    one line, shown under the title
check:   tmux                 # a command name. On PATH -> "*", missing -> "-"
install: sudo dnf install tmux
docs:    man tmux
probe:   tmux                 # optional — see "Probes" below
conf:    ~/.tmux.conf         # which config the probe reads

= SESSIONS — a group heading; the part after the dash is optional
@detach-client   | and everything inside keeps running
Ctrl-a d         | a literal row, when there is nothing to probe
```

- `key | description`, split on the first **unescaped** `|`. Write a literal
  pipe as `\|`, which is what makes `rg -l x \| xargs sed` a legal row.
- `= TITLE` starts a group. Everything after it belongs to it until the next.
- `#` at the start of a line is a comment. Blank lines are ignored.
- Metadata fields normally go before the first `=`. A group may set `probe:`
  inside the group to use a different live reader; `conf:` still names the
  document's probe source.
- **Omit `check:`** for something that is not a command — the shell's own line
  editing, this repo's scripts. Those are never reported as missing.
- `install:` is shown only when `check:` fails, which is what makes the list
  double as a queue of what you have not set up yet.

## `@action` — why a shipped file holds no keys

A row that starts with `@` names an **action**, not a key. The key column is
filled in at view time by running the probe and asking the tool what it is bound
to *on this machine*.

```
@split-window -h | a pane beside this one
```

That renders `Ctrl-a |` here and whatever you bound it to on your machine. So a
file in this public repo can describe tmux without shipping anybody's personal
bindings as if they were upstream defaults — which is the whole point.

- Several keys may resolve to one action; they are shown joined.
- An action nothing is bound to renders dimmed as `unbound`. You unbound it;
  that is information, not an error.
- A probe that cannot run says so once at the top of the panel, and the literal
  rows still render.

**A shipped file carries upstream defaults or `@action` rows — never your own
config.** If a tool has no probe (lazygit, zellij), write the upstream defaults
literally and say in a comment why there is no probe. A degraded probe that
renders every row `unbound` is worse than no probe at all.

## Probes

`probe:` names the source; `conf:` names the file it reads. A group may override
`probe:` on its own line, so one file can mix a probed group with literal ones.

| `probe:` | reads | joins on |
|---|---|---|
| `tmux` | `tmux -f <conf> list-keys` | the tmux command (`split-window -h`) |
| `toml-actions` | superfile's `hotkeys.toml` | the action name (`confirm`) |
| `git-alias` | `git config --get-regexp '^alias\.'` | the alias name |
| `vim-map` | `vim -N -u <conf> -es -c 'map'` | the mapped command |
| `shell-alias` | `$SHELL -ic alias` | the alias name |
| `yaml-keys` | lazygit's `config.yml` | the action path |
| `kdl` | zellij's `config.kdl` | the action |
| `help` | `<name> --help` — flags **and** subcommands | the command itself |

Probing is lazy and cached for the session; the cache `stat`s its source before
reuse, so editing a config in another pane is picked up with no keystroke. `r`
re-probes the focused view, `R` everything.

Two header fields exist only for the `help` probe:

- `subcommands: git help -a` — where the subcommand list really is, when
  `--help` does not have it.
- `help_cmd: gh {} --help` — how to ask a *node* for its own help, when it is
  not `<node> --help`.

## Nesting

Indentation is nesting, two spaces a level, to any depth:

```
@gh pr create    | open a PR from the current branch
  --fill         | title and body from the commits
  --draft        | mark it draft
```

A node with children opens on `enter` and closes on `h`. A `help`-probed node
with **no** written children fetches them by running its own `--help` the first
time you open it — one node, on demand. Never a tree walk: 20 `git <sub> --help`
calls took 1847 ms here, so git's 178 subcommands would be ~16 s.

Search opens the ancestors of every match, so a hit never hides behind a closed
parent. A row indented more than one level past its parent is reported as a data
error at load, not silently reparented.

Leave `= ALL FLAGS (from --help)` last and empty in a `help` file: the probe
fills it, and it sits at the bottom so `rg`'s 149 flags are reachable without
being the first thing you read.

## Three layers

The unit of override is one file — one *(tool, view)* pair. Highest layer wins,
whole file; there is no row-level merging.

| | layer | holds |
|---|---|---|
| 3 | `~/.config/howto/` | yours. Wins |
| 2 | `~/.config/howto/generated/` | what the SCAN tab wrote |
| 1 | `howto/data/` | this directory — shipped, public, in git |

`howto where <tool>` lists every layer, winner first, and the panel header names
the winning layer when it shadows a lower one. `howto edit <tool>` copies the
winner up into `~/.config/howto/` and opens `$EDITOR`, so a generated stub you
have filled in becomes yours and re-scanning never disturbs it.

Because probeable rows hold `@action`, the shipped file already tracks your
rebinds. You need your own layer when you want different **content** — different
rows, different words — never merely different keys.

## Starting a new file

```
howto new zellij --help
```

copies `howto/templates/tool.help` into `~/.config/howto/`, prefilled, and
refuses to overwrite. The templates are commented and carry one worked row of
each kind — they are the format in executable form, and they are what you hand
to an agent: *"fill this in for zellij from its docs."*

## Configuring howto

`howto config` copies four commented files into your config directory and
never overwrites one already there. Tables merge over the shipped files;
scalars and lists replace them.

- `hotkeys.toml` binds every action and drives dispatch, the `?` overlay and
  the footer from the same table.
- `tools.toml` says what SCAN looks for.
- `theme.toml` maps the eight display roles to terminal colours.
- `config.toml` controls pane sizes, probe timeout and generated-stub limits.

Two habits worth keeping:

**Document the config in this repo, not the manual.** `tmux/tmux.conf` rebinds
the prefix to `Ctrl-a` and splits with `|` and `-`, so the tmux rows are
`@split-window -h`, which reads back as `Ctrl-a |` — not the upstream
`Ctrl-b %`. A cheatsheet that disagrees with the machine is worse than none.

**Write the description as why, not what.** "detach, and everything inside keeps
running" earns its line. "detach the client" repeats the key name.
