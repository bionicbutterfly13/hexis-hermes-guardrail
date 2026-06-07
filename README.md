# Hexis Hermes Guardrails

Metacognitive command guardrails for AI coding agents, ported from the
[Hexis framework](https://github.com/hexis-framework/hexis). One shared rule set
turns repeated agent mistakes into enforceable behavior:

```text
observation → soft rule → reminder → violation log → repeat violation → hard gate
```

It runs **across agents** — Claude Code, Codex CLI, Cursor, and Hermes — from a
single pure core, and never patches any host. Each agent keeps its own native
config; the guard plugs into the pre-command hook the agent already exposes.

## Supported platforms

| Platform | How it hooks in | Where |
|---|---|---|
| **Claude Code** | `PreToolUse` hook (matcher `Bash`) | `~/.claude/settings.json` |
| **Codex CLI** | `PreToolUse` hook (matcher `^Bash$`) | `~/.codex/hooks.json` |
| **Cursor** | `beforeShellExecution` hook (`failClosed`) | `~/.cursor/hooks.json` |
| **Hermes** | native in-process directory plugin | `~/.hermes/plugins/hexis/` |

The three hook-based agents share **one** installed core at
`~/.hexis-guardrails/` plus a launcher they all point at, so a single update
covers them all. Hermes loads the same core in-process via a thin adapter.

## What it provides

| Guardrail | What it does (heuristic) | Default |
|---|---|---|
| Credential reads | Flags common reads of `.env`/`.pem`/SSH/`.netrc`/cloud creds by common readers | `block` |
| Force-push to `main`/`master` | Flags `--force`/`-f`/`--force-with-lease`/`+ref` to main/master | `block` |
| `rm -rf` | Flags destructive `rm` with `-r`/`-f` | `warn` |
| Unscoped search | Flags `grep`/`rg`/`find`/`fd` rooted at the home **root** | `warn` |
| Package-manager mismatch | Warns when `npm` mutates a pnpm/yarn/bun project | `warn` |
| Stuck-loop detection (Hermes) | Repeated calls, repeated errors, A-B-A-B oscillation | `warn/log` |

Guards fire **only** on shell/terminal commands. They are heuristic
defense-in-depth, **not a security boundary** — each host's own approval/credential
gate is the real boundary. Full rule reference: [`hexis/README.md`](hexis/README.md).

## Requirements

Python 3.9+, plus at least one supported agent installed. The interactive picker
uses [`questionary`](https://pypi.org/project/questionary/) (pulled in by pip); you
can skip it entirely with `--all` / `--platform`.

## Install

```bash
pip install hexis-hermes-guardrails
hexis-hermes-guardrails install          # checkbox-pick platforms (detected ones pre-checked)
```

Non-interactive forms:

```bash
hexis-hermes-guardrails install --all                       # every detected/supported platform
hexis-hermes-guardrails install --platform claude-code,codex
hexis-hermes-guardrails install --dry-run --all             # show the plan, change nothing
HEXIS_PLATFORMS=cursor hexis-hermes-guardrails install --no-input
```

Per-platform follow-ups the installer prints for you:

- **Codex** — ensure `[features] hooks = true` in `~/.codex/config.toml`; the
  first run prompts you to trust the hook.
- **Cursor** — installed with `failClosed: true` (Cursor defaults to fail-*open*;
  a guard must fail *closed*).
- **Hermes** — enable the plugin in `~/.hermes/config.yaml`
  (`hexis-hermes-guardrails config` prints the block):

```yaml
plugins:
  enabled:
    - hexis
  entries:
    hexis:
      guards:
        rm_rf: warn
        unscoped_search: warn
        credential_read: block
        force_push_main: block
        pkg_manager_mismatch: warn
      stuck_loop:
        enabled: true
        surface_to_model: false
```

For the hook platforms, set the same per-guard modes in
`~/.hexis-guardrails/config.json` (or point `$GUARDCORE_CONFIG` at a file):

```json
{ "guards": { "credential_read": "block", "rm_rf": "warn" } }
```

## Manage

```bash
hexis-hermes-guardrails status      # what's detected / installed
hexis-hermes-guardrails update      # re-sync the shared core to installed platforms
hexis-hermes-guardrails uninstall   # remove the guard (Hermes keeps its state/)
```

Auto-update is **off by default** — a control that can block every shell command
should not silently change itself. Run `update` when you choose to.

## Verify

- **Unit suite** — `python3 -m unittest discover -s tests -t .` (pure stdlib, no
  deps). Covers the core rules, the universal hook's per-platform deny/allow
  shapes against recorded payloads, and the installer's config writes.
- **`scripts/smoke-test.sh`** — *hermetic*. Installs into a throwaway
  `HERMES_HOME`, compiles, checks hook + skill registration and representative
  `block`/`warn` behavior, then uninstalls. Never touches your real profile.
- **`python3 scripts/verify_live_runtime.py`** — *integration*. Drives a **live**
  Hermes runtime (real loader, hook registry, dispatch, config, violation log)
  and confirms the guard contract end-to-end. SKIPs cleanly if Hermes is absent.

CI runs the unit suite + smoke test on Python 3.9–3.12 and a build/metadata check
(`.github/workflows/tests.yml`).

## Layout

```text
guardcore/                 platform-agnostic core (pure, stdlib only)
  guards.py                command guards (credential/force-push/rm/search/pkg)
  stuck.py                 stuck-loop detector
  violations.py            durable violation + tool-call logs (state dir injected)
  hook.py                  universal subprocess hook (Claude Code / Codex / Cursor)
hexis/                     Hermes adapter — register(ctx) + hooks; vendors guardcore
  __init__.py, plugin.yaml, README.md, SKILL.md
hexis_hermes_guardrails/   multi-platform installer CLI
  cli.py                   install / update / uninstall / status / config
  platforms.py             per-platform detect + idempotent config writers
tests/                     unittest suite (guards, hook, installer)
scripts/
  install.sh / uninstall.sh        Hermes checkout install
  smoke-test.sh                    hermetic install/uninstall test
  verify_live_runtime.py           live-runtime integration validation
.github/workflows/         tests.yml (CI), publish.yml (PyPI trusted publishing)
pyproject.toml             packaging
LICENSE                    MIT
```

## Architecture

Ports-and-adapters: `guardcore` knows nothing about any agent — it exposes
`guards.evaluate(command, modes, …) → {"action":"block",…} | None`. A platform
*adapter* translates that agent's hook payload into a call and the decision back
into that agent's response shape. The subprocess agents converged on one
contract — pending command as JSON on stdin, a deny as a JSON decision on stdout —
so they share a single `guardcore.hook` entry point; only the field names and the
deny JSON shape differ. Hermes is in-process Python. Adding a new agent is a new
adapter, not a new core.

## License

MIT — see [`LICENSE`](LICENSE). Independent port of [Hexis](https://github.com/hexis-framework/hexis) (MIT); see the Credit section of `hexis/README.md`.
