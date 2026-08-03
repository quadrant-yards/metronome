# metronome — setup brief

## What this is

`metronome` is a single repo that ships two different kinds of thing to your client
projects:

- **Claude skills** — invoked by Claude Code inside a project
- **Python modules** — imported by code inside a project

These are two independent delivery channels that happen to live in one repo. They don't
interact: skills are *discovered at a filesystem location* by the agent runtime, Python is
*imported into a project's virtualenv*. `metronome` wears both hats at once, and that's fine.

## The approach (and why local)

Both channels support a "local" mode (point consumers at your on-disk checkout) and a
"git" mode (point consumers at a GitHub source). The tradeoff is the same for both:

> **Local is a fact about your laptop. Git is a fact about the repo.**

Local mode is invisible to the client repos and only resolves on the machine where the
checkout lives — but it's the better developer experience because edits are live and there's
nothing to publish. Since **metronome runs on one machine only**, local is the correct call
for both channels. No git source, no version pins, no publishing step.

If a second machine, a collaborator, or CI ever enters the picture, there's a clean escape
hatch (see the last section) — but nothing below changes structurally when that happens.

## Repo layout

```
metronome/
├── .claude-plugin/
│   └── marketplace.json          # skills channel: the catalog
├── .python-version                # pins this repo's Python version for uv (e.g. "3.13")
├── plugins/
│   └── metronome-skills/         # one plugin, holds all skills
│       ├── .claude-plugin/
│       │   └── plugin.json
│       └── skills/
│           └── <skill-name>/
│               └── SKILL.md
├── src/
│   └── metronome/                # python channel: the importable package
│       ├── __init__.py
│       └── <module>.py
└── pyproject.toml                # makes the python installable
```

Names to keep straight (they're allowed to differ and it reduces confusion if they do):

| Thing | Value | Where it's used |
|---|---|---|
| Marketplace name | `metronome` | after the `@` when installing |
| Plugin name | `metronome-skills` | before the `@`; namespaces the skills |
| Python import name | `metronome` | `import metronome` |

Skills end up invoked as `/metronome-skills:<skill-name>`.

## Manifest contents

`.claude-plugin/marketplace.json`:

```json
{
  "name": "metronome",
  "owner": { "name": "Sam" },
  "plugins": [
    {
      "name": "metronome-skills",
      "source": "./plugins/metronome-skills",
      "description": "Reusable Claude skills for client work"
    }
  ]
}
```

The `source` is relative and must start with `./`. It resolves against the marketplace root
(the directory containing `.claude-plugin/`), **not** against the `.claude-plugin/` dir
itself — this is the one gotcha that produces "Plugin directory not found" errors.

`plugins/metronome-skills/.claude-plugin/plugin.json`:

```json
{
  "name": "metronome-skills",
  "description": "Reusable Claude skills",
  "version": "0.1.0"
}
```

`pyproject.toml`:

```toml
[project]
name = "metronome"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/metronome"]
```

## Setup steps

The repo lives at `~/ghq/github.com/quadrant-yards/metronome` (already created, already a git
repo — see below). The only current consumer is `~/ghq/github.com/quadrant-yards/engagements`,
a single repo with `sealed/` and `david-energy/` as subdirectories, not two separate repos.

All Python tooling on this machine, for both `metronome` itself and its consumers, is `uv`
(Astral's Python tool) — there is no shared global environment. `metronome`'s own dev
environment lives in its repo-local `.venv/`. Consumers don't install `metronome` into
anything; standalone scripts declare it as a dependency directly in their own PEP 723 inline
script metadata (a `# /// script` header block) with a local path source pointing at this repo,
and run independently via `uv run <script>.py`.

### 1. Create metronome's own dev environment

```bash
cd ~/ghq/github.com/quadrant-yards/metronome
uv python pin 3.13
uv sync --extra dev
```

`uv python pin 3.13` writes a plain version string (`3.13`) to the `.python-version` file at
the repo root, installing a uv-managed 3.13.x interpreter first if one isn't already available.
`uv sync --extra dev` then creates a repo-local `.venv/` and installs both the base and `dev`
(e.g. `pytest`) dependency groups, pinned via `uv.lock`. Development and testing of `metronome`
itself — and any dev-only dependencies — happen here, never in `pyme`.

### 2. Add the files

The repo and its `.git` already exist, so this is just filling in the missing pieces on top of
what's there:

```bash
cd ~/ghq/github.com/quadrant-yards/metronome
mkdir -p .claude-plugin plugins/metronome-skills/.claude-plugin plugins/metronome-skills/skills src/metronome
touch src/metronome/__init__.py
# then create marketplace.json, plugin.json, pyproject.toml with the contents above
```

Add at least one skill so there's something to install — e.g.
`plugins/metronome-skills/skills/example/SKILL.md` with YAML frontmatter and a body.

### 3. Validate the skills channel

```bash
cd ~/ghq/github.com/quadrant-yards/metronome
claude plugin validate .
```

Fix any JSON / frontmatter errors it reports before continuing.

### 4. Register the skills channel (once, machine-wide)

```bash
claude plugin marketplace add ~/ghq/github.com/quadrant-yards/metronome
claude plugin install metronome-skills@metronome
```

Because this is registered at user scope, the skills are now available in **every** Claude
Code session on this machine — `engagements` and anything future — with zero per-client
config.

### 5. Wire up a consumer script

Add a PEP 723 header to the top of the consuming script, declaring `metronome` as a dependency
with a local path source pointing at this repo:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "metronome",
# ]
#
# [tool.uv.sources]
# metronome = { path = "/Users/sam/ghq/github.com/quadrant-yards/metronome" }
# ///
import metronome
```

No install step, no shared env — each script resolves `metronome` independently the first time
it's run with `uv run <script>.py`.

### 6. Verify

Python:

```bash
uv run <script>.py
```

`uv` should report building/installing `metronome` from the local path on first run. Add
`print(metronome.__file__)` to the script temporarily to confirm the resolved path points back
into `~/ghq/github.com/quadrant-yards/metronome/src/metronome`.

Skills — open Claude Code inside `engagements` and confirm `/metronome-skills:` shows your
skill(s) in the slash-command list.

## Day-to-day workflow

**Editing a Python module** — `cd` into `metronome` and edit `src/metronome/…`; run things with
`uv run <command>` (e.g. `uv run pytest`) so they execute against the repo's own `.venv`
without needing to activate it manually. Since consumer scripts point at this repo via a local
path source (not an installed copy), `uv run` rebuilds from source each time, so the change is
live for consumers immediately too — nothing to reinstall. Any dev-only dependencies (test
runner, linter, etc.) get added to `metronome`'s own environment via `uv add --dev <package>`.

**Editing or adding a skill** — this is the one asymmetry to remember. Skills are **copied
into a cache** on install (`~/.claude/plugins/cache`), so unlike Python they are *not* live
after an edit. Refresh with:

```bash
# inside Claude Code
/plugin marketplace update
/reload-plugins
```

If a change still doesn't show, re-run `/plugin install metronome-skills@metronome` to
rebuild the cached copy. (Bumping `version` in `plugin.json` on each meaningful change makes
this deterministic; leaving it fixed can cause an update to be skipped as "same version.")

You only ever edit `metronome`. `engagements` never changes once wired.

## If the one-machine assumption breaks

Nothing in the layout above changes — you only swap *local sources* for *git sources* in the
two places consumers point at:

- **Skills**: instead of `claude plugin marketplace add ~/ghq/github.com/quadrant-yards/metronome`, commit a
  `.claude/settings.json` into each client with `extraKnownMarketplaces` →
  `{ "source": "github", "repo": "you/metronome" }` and `enabledPlugins`.
- **Python**: instead of a local `path` source in each consumer's `[tool.uv.sources]`, point at
  a git ref pinned to a tag or SHA, e.g.
  `metronome = { git = "https://github.com/quadrant-yards/metronome", tag = "vX.Y.Z" }`.

At that point you'd start tagging releases in `metronome`. Until then, local is simpler and
strictly better for iteration.