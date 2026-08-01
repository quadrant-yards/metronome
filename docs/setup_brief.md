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
├── .python-version                # pins this repo's shell to the `metronome` pyenv env
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

Python tooling on this machine is `pyenv` + `pyenv-virtualenv`, not `uv` (`uv` isn't installed
here). There's a single shared virtualenv, `pyme`, set as the default for the entire `~/ghq`
tree via `~/ghq/.python-version` — `engagements` inherits it and has no env of its own. So the
Python channel is wired **once**, globally, by editable-installing `metronome` into `pyme`.

`metronome` gets its own virtualenv, separate from `pyme`, so developing the package never
happens inside the shared consumer env — same pattern as the existing `sealed` and `ds` envs.

### 1. Create metronome's own dev environment

```bash
pyenv virtualenv 3.13.9 metronome
cd ~/ghq/github.com/quadrant-yards/metronome
pyenv local metronome
```

`pyenv local` writes a `.python-version` file containing `metronome` at the repo root. Since
pyenv resolves the nearest `.python-version` walking up from the cwd, any shell `cd`'d into
this repo now uses the `metronome` env instead of the `pyme` env it would otherwise inherit
from `~/ghq/.python-version`. Development and testing of `metronome` itself — and any
dev-only dependencies — happen here, never in `pyme`.

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

### 5. Install `metronome` into `pyme` (the consumer env)

```bash
~/.pyenv/versions/3.13/envs/pyme/bin/pip install -e ~/ghq/github.com/quadrant-yards/metronome
```

This is a one-time editable install into `pyme` specifically — run with `pyme`'s own `pip`
binary so it lands there regardless of which env the current shell has active. Because `pyme`
is the default env for all of `~/ghq`, `import metronome` now works from any repo under
`~/ghq` (including `engagements`, `sealed/`, `david-energy/`) with no per-repo wiring.

### 6. Verify

Python — from inside `engagements` (or anywhere else under `~/ghq`, since `pyme` is global):

```bash
python -c "import metronome; print(metronome.__file__)"
```

The path should point back into `~/ghq/github.com/quadrant-yards/metronome/src/metronome`.

Skills — open Claude Code inside `engagements` and confirm `/metronome-skills:` shows your
skill(s) in the slash-command list.

## Day-to-day workflow

**Editing a Python module** — `cd` into `metronome` (its own `.python-version` auto-switches
the shell to the `metronome` env) and edit `src/metronome/…`. The editable install in `pyme`
means the change is live everywhere under `~/ghq`, including `engagements`, immediately.
Nothing to reinstall. Any dev-only dependencies (test runner, linter, etc.) get installed into
`metronome`, not `pyme` — `pyme` only ever needs what consumers of the package need.

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
- **Python**: instead of the one-time editable `pip install -e` into `pyme`, `pip install` a
  git-based ref pinned to a tag or SHA, e.g.
  `pip install "metronome @ git+ssh://git@github.com/quadrant-yards/metronome.git@vX.Y.Z"`.

At that point you'd start tagging releases in `metronome`. Until then, local is simpler and
strictly better for iteration.