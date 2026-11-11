# The Mothership

One install that gives every AI tool on your computer the same memory and the same thrifty habits.

It brings together two separate open-source products and sets them up to work with each other:

- **Skeleton Base**: your knowledge base ("second brain"), a plain
  folder of Markdown files. Every AI tool you use reads it to know who you are and what you are working on, and
  saves what it learns there.
- **Frugal-Bridge**: short rules (and small hooks) that make AI tools
  use fewer tokens without doing worse work.

Both live in their own repositories next to this one (same GitHub owner); a copy of each, pinned to one commit,
is inside this repository under `components/`. Python 3.10+ standard library only. No account, no server, no package installs, no network needed to install.
Linux and macOS.

## Quick start

```sh
git clone <this repository's URL> the-mothership
python3 the-mothership/install.py --yes
```

That is all. Then:

1. Open `~/skeleton-base-home/hot.md` (what matters now) and `~/skeleton-base-home/maps/brain.html` (a mind map of
   your base, opens in any browser, works offline).
2. Ask any AI tool, in any folder: *"interview me and fill wiki/me/, one question at a time"*.

Without `--yes` it asks where the base should live (default `~/skeleton-base-home`) and whether to start the
background watcher. `--dry-run` shows the plan and writes nothing.

```sh
python3 the-mothership/install.py --base ~/notes/brain     # another folder for the base (see below for spaces)
python3 the-mothership/install.py --no-frugal              # only the knowledge base
python3 the-mothership/install.py --no-watch [--timer]     # no watcher service (or only a daily timer)
python3 the-mothership/install.py --mcp                    # also register the base's MCP server in each tool
python3 the-mothership/install.py --verbose                # also show both products' own output
```

A base path with spaces works, with or without Frugal-Bridge (both products write and read it quoted, for
example `Path: "/home/you/my notes"`). Only a Frugal-Bridge that cannot read a quoted path (one without
`parse_base_path` in its `kit/setup.py`, older than the vendored one) makes the installer refuse such a path,
before writing anything; `--no-frugal` or a path without spaces then works.

Running it again changes nothing (byte for byte). If an install is interrupted, run the same command again: it
continues. If a step fails on a first install, everything it did is undone.

## What gets installed where

| what | where |
|---|---|
| your knowledge base (Skeleton Base) | `~/skeleton-base-home/` (or `--base DIR`) |
| Frugal-Bridge rules for that folder | inside the base's `AGENTS.md`, in its own marked block after the base block |
| a pointer to the base + Frugal-Bridge rules in each AI tool's user-level rules file, for **every tool found** | one file per tool, the one that tool loads (e.g. `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md`, `~/.qwen/QWEN.md`, `~/.config/opencode/AGENTS.md`, Hermes `SOUL.md` when it exists, and the other rows of both products' tool tables): each product only adds its own marked block, base first, your text stays as it is |
| the base on each tool's own allow list (read + write from any folder) and, with `--mcp`, the base's MCP server in each tool's MCP config | each tool's own setting (Skeleton Base `connect`), recorded and removed by `disconnect` |
| Frugal-Bridge hooks / plugins and helper tiers (cheap / mid / top: model **and** effort for your provider) per tool | each tool's own hook, plugin and subagent files (Frugal-Bridge `install --global --hosts auto`) |
| Claude Code hooks (collect memories at session end, Frugal-Bridge context watch) and read access to the base from any folder | merged into `~/.claude/settings.json` (your keys and hooks are kept) |
| Frugal-Bridge user-level files | `~/.frugal-bridge/` (`FRUGAL_HOME` moves it): its hook and `global.json`. Your profile lives in the base (`wiki/me/`), so there is no second user file |
| the base's pointer file (other kits find the base there, even when no tool rules file names it) | `~/.config/skeleton-base/base`: one line, the base folder |
| watcher + daily collect (Linux) | `~/.config/systemd/user/skeleton-base-watch.service`, `skeleton-base-collect.timer`; with `--yes` they are enabled when `systemctl --user` works, otherwise the command to enable them is printed |
| a stable copy of The Mothership (so you can delete the clone) | `~/.local/share/the-mothership/` (`XDG_DATA_HOME` or `MOTHERSHIP_HOME` move it) |
| the install record | `~/skeleton-base-home/.mothership.json` |

On macOS the watcher is skipped and said so; the session hooks still collect, and
`python3 ~/skeleton-base-home/tools/brain.py watch` runs the watcher by hand.

Already have a Skeleton Base or Frugal-Bridge? They are found and **adopted**, never installed twice. A
Frugal-Bridge profile (`~/.frugal-bridge/USER.md`) is merged into `wiki/me/` (nothing is overwritten; anything
unclear lands on a review card in `board/`). An adopted base is **never downgraded**: when its Skeleton Base
release (`.kits.json` `kits.base-folder.release`, or the `RELEASE` line of its `tools/brain.py`) is newer than the
vendored one, it is kept as it is and the summary says so; `--force` installs the vendored version over it.

## Which tools, which provider

Any tool, any provider. Both products keep one tool table each, and The Mothership simply runs them for every tool
it finds (a tool counts as installed when its program is on `PATH` or its own config file exists):

- what the base gives each tool (finds the base, reads + writes it, its memory collected, MCP):
  [Skeleton Base's tool matrix](components/skeleton-base/README.md#connect-every-tool-on-this-computer-knows-the-base)
- what Frugal-Bridge sets up in each tool (rules, hooks / plugin, output filter, helper tier model + effort, usage
  log, proxy): [Frugal-Bridge's matrix](components/frugal-bridge/adapter/README.md#every-tool-what-install---global-sets-up-the-matrix)

## Check, status, update

```sh
python3 ~/.local/share/the-mothership/payload/install.py check    # names each problem; exit 1 on install problems
python3 ~/.local/share/the-mothership/payload/install.py status   # what is installed, versions, connected tools
python3 ~/.local/share/the-mothership/payload/install.py report 7 # tokens per tool and model, last 7 days
```

`report` is Frugal-Bridge's usage report: what its hooks, plugins and proxy logged for every tool.

`check` runs both products' own checks, `brain.py lint`, and its own: one base block and one Frugal-Bridge block
per rules file (base first), Frugal-Bridge uses the base as its only user file, the watcher is running, and the
vendored files match `components.lock`. Only those install problems make it exit 1 (`FAIL` lines). `brain.py
lint` checks your own pages (front matter, links, file names); what it finds is listed as `WARN` lines and never
fails `check` or `install` (install exits 0 with the list). It may ask you to run `python3 tools/brain.py index`
in the base after you add pages.

Update to a newer version: get the new version of this repository (`git pull`), then

```sh
python3 the-mothership/install.py update
```

It applies the new Skeleton Base and Frugal-Bridge versions to your install with your earlier choices. Your pages,
sources, cards and edited files are left alone; product files you never changed are upgraded.

## Uninstall

```sh
python3 ~/.local/share/the-mothership/payload/install.py uninstall
```

It undoes everything in reverse order, using each product's own uninstall, and gives your files back byte for
byte: rules files, settings (including their original layout), systemd units and folders it created.
Pages you wrote stay in the base folder. Anything that was there before The Mothership (an adopted base or
Frugal-Bridge) stays installed.

## Uninstall keeps your data

Removing The Mothership (or Skeleton Base) never deletes anything of yours.

- **Full backup first.** Before anything is undone (the watcher is stopped first, so nothing writes meanwhile),
  the whole base, `.git` and dotfiles included, goes to `~/skeleton-base-backups/NAME-YYYYmmdd-HHMMSS.tar.gz`
  (mode 600, folder 700, outside the base, read back and checked). The path and a one-line restore command
  (`mkdir -p PARENT && tar -xpzf ARCHIVE -C PARENT`) are printed. If the backup cannot be written, nothing is
  uninstalled. `--backup-dir DIR` picks another folder (never inside the base); `--no-backup` skips it, only when
  you give it.
- **Only unmodified product files go.** Wiki pages, `raw/` (also `raw/inbox/collected/`), board cards, agents,
  `hot.md`, `progress/agents.log`, maps and templates you edited, Frugal-Bridge skill files you edited, `.brain/`
  (collector state, backups), files of any other type and the git repository with its whole history (not even an
  empty folder in `.git` is touched) stay exactly as they were. In shared files (`AGENTS.md`, `CLAUDE.md`,
  `GEMINI.md`, `.gitignore`, the tools' rules files in your home) only the products' marked blocks are removed;
  in JSON settings only the keys they added.
- **Safety net.** If a product's uninstall ever removed a file of yours anyway (one that is not a product file
  byte for byte), The Mothership puts it back from the backup archive and says so.
- **Backup copies the products made** while installing and uninstalling are moved into
  `~/skeleton-base-backups/NAME-product-backups-TIME.tar.gz` (mode 600), not deleted (`--keep-backups` leaves
  them where they are).
- **Afterwards it prints what was kept and where** (per folder, with the git history), and that the folder is
  plain Markdown: any AI tool can open it as it is, and `install.py --base DIR` (or Skeleton Base's
  `brain.py init DIR`) adopts it again without overwriting or duplicating anything.
- **`update`** re-runs both products' setups: your pages and edited files are left alone, and a Frugal-Bridge
  skill file you edited is not overwritten by the new version.
- **A failed install** is rolled back without touching what was in the folder before (a backup of a non-empty
  folder is written before installing into it).
- **`--purge`** (delete the base) asks you to type the base's folder name (non-interactive:
  `--yes-purge-NAME`, e.g. `--yes-purge-skeleton-base-home`), refuses `--no-backup`, writes the full backup first
  and only works for a base The Mothership created.

## FAQ

**Does it work with my AI tool?** Yes, with any tool, model or provider. Tools that read a user-level rules file
get the pointer automatically, and tools that keep their agent in the folder it started in get the base added to
their own allowed folders, so they read and write it from anywhere (Skeleton Base's README has the tool-by-tool
matrix). Nothing in the install needs a model or a provider. A tool you install later is connected to the base by the watcher; run
`install.py` again to give it the Frugal-Bridge rules too. Tools that only take
pasted instructions (chat apps): run `python3 ~/skeleton-base-home/tools/brain.py brief` and paste the output. No
tool or agent name is required anywhere.

**Does anything leave my machine?** No. The install needs no network, nothing calls home, and the base is plain
files in a folder you own. Your AI tools read it the same way they read any file you show them.

**Why is everything vendored?** So the install is offline, reproducible, and checked: `components.lock` holds the
commit and a hash of every file of both products, and the installer refuses to run if anything differs. See
[docs/DESIGN.md](docs/DESIGN.md).

**Can I use the products without The Mothership?** Yes. Both are standalone; The Mothership only runs their own
setups in the right order.

## For maintainers

```sh
python3 -m unittest -v                                # the whole suite (isolated temp HOMEs; touches nothing real)
MOTHERSHIP_BLOCKED_WORDS=~/my-words.txt python3 -m unittest tests.test_mothership.PublicTests
MOTHERSHIP_REAL_CLAUDE=1 python3 -m unittest tests.test_mothership.RealToolTests   # real `claude -p` cold start
python3 tools/update-components.py                    # re-vendor both from GitHub, rewrite components.lock
MOTHERSHIP_BLOCKED_WORDS=~/my-words.txt python3 tools/update-components.py   # leave out upstream files with those words
python3 tools/update-components.py --check            # verify the vendored files
```

The suite also runs both products' own test suites from the vendored copies (Frugal-Bridge's pytest-style tests
through `tests/pytest_adapter.py`, no pytest needed).

License: MIT, see [LICENSE](LICENSE). The two vendored components keep their own MIT licenses and copyright
notices: [components/skeleton-base/LICENSE](components/skeleton-base/LICENSE) and
[components/frugal-bridge/LICENSE](components/frugal-bridge/LICENSE). See [CHANGELOG.md](CHANGELOG.md).
