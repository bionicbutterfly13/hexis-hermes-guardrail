# Hexis Metacognitive Guardrails for Hermes Agent

`hexis-hermes-guardrails` is an update-safe Hermes Agent plugin that ports the
portable parts of the [Hexis framework](https://github.com/hexis-framework/hexis)
into Hermes-native runtime guardrails.

Hexis turns repeated agent mistakes into enforceable behavior through an
escalation loop:

```text
observation -> soft rule -> reminder -> violation log -> repeat violation -> hard gate
```

This plugin implements that loop for Hermes without patching Hermes core.

## Not a Security Boundary (read this first)

These guards are **heuristic, regex/token-based, defense-in-depth — they are NOT
a security boundary.** They inspect the literal `terminal` command string and can
be bypassed (e.g. unusual readers, shell obfuscation, quoting tricks). Hermes core
(`tools/credential_files.py`, `tools/approval.py`) is the real credential/approval
gate; hexis is a best-effort second layer that catches the *common* shapes of risky
commands and routes them into the escalation loop. A `block` here means "refuse the
obvious case," not "guarantee X can never happen." Guards only fire on the
**`terminal`** tool. If a guard is wrong for your workflow, set it to `warn` or `off`.

## What This Provides

| Guardrail | What it does (heuristic) | Default |
|---|---|---|
| Credential guardrails | Flag common reads of `.env`/`.envrc`, `.pem`/`.key`, SSH material, npm/pypi/netrc, `.git-credentials`, `.p12`/`.pfx`, `.tfvars`, kube/docker config by common readers (`cat`/`grep`/`cp`/`scp`/`dd`/`python -c`/…). Common forms only — not exhaustive. | block |
| Git guardrails | Flag force-pushes that target `main`/`master` (incl. `--force`, `-f`, `--force-with-lease`, the `+ref` refspec, and remote-only/no-branch force-pushes). | block |
| Package-manager guardrails | Warn when `npm install/i/add/ci/remove/rm/uninstall/un/unlink` runs in a pnpm/yarn/bun project. | warn |
| Search-scope guardrails | Warn on broad `grep`/`rg`/`ack`/`find`/`fd` rooted at the home **root** (`~`, `$HOME`, `/Users/<name>`, `/home/<name>`) — scoped subdirs are not flagged. | warn |
| Delete guardrails | Warn on `rm` with `-r`/`-f` flags (quoted filenames and args after `--` are not flagged). | warn |
| Stuck-loop guardrails | Detect repeated tool calls, repeated errors, and A-B-A-B oscillation. | warn/log |
| Escalation | Record violations and use `hexis:enforce` to graduate repeated `warn` rules to `block`. | human-curated |

The code handles mechanical detection. The `hexis:enforce` skill keeps the
judgment with the human: when a `warn` rule becomes a hard `block`, where a
lesson belongs, and when a guard should be removed because it creates friction.

## Why It Survives Hermes Updates

- Lives under `~/.hermes/plugins/hexis/`, outside the `hermes-agent/` checkout.
- Patches no Hermes core files.
- Uses Hermes plugin surfaces: `register_hook` and `register_skill`.
- Is opt-in: add `hexis` to `plugins.enabled`.
- Is disableable: remove `hexis` from `plugins.enabled`.

## Install From A Local Checkout

Until a PyPI package exists, copy this plugin directory into the active Hermes
profile:

```bash
mkdir -p ~/.hermes/plugins
cp -R hexis ~/.hermes/plugins/hexis
```

Enable it in `~/.hermes/config.yaml`:

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

## Future PyPI Package

The planned PyPI package name is `hexis-hermes-guardrails`. That avoids the
upstream `hexis` namespace while saying exactly what this project is.

A PyPI release should install a small command, for example:

```bash
pip install hexis-hermes-guardrails
hexis-hermes-guardrails install
```

The installer should copy or symlink the Hermes plugin into
`~/.hermes/plugins/hexis/` and print the config block above. Installing a Python
package alone is not enough because Hermes discovers user plugins from the
Hermes profile plugin directory.

## State Files

Runtime state is profile-local and git-ignored:

- `~/.hermes/plugins/hexis/state/rule-violation-log.jsonl`
- `~/.hermes/plugins/hexis/state/rule-violation-log.md`
- `~/.hermes/plugins/hexis/state/tool-call-log.jsonl`

The durable tool-call log stores tool name, session id, tool call id when
present, a stable signature, and a short error snippet. Raw tool arguments are
**never** written (only a SHA-1 signature). Error snippets are truncated and
redacted for common secret patterns (`sk-…`, `gh*_…`, `AKIA…`, `xox*-…`,
`password=`/`token=`/`bearer`) on a best-effort basis — treat the log as
low-sensitivity, not a guaranteed secret-free store. The violation logs are
append-only and **not rotated**; on a long-lived install they grow unbounded
(the rolling tool-call log is capped at 50 rows).

## What Was Not Ported

Some upstream Hexis artifacts are intentionally not copied into Hermes:

| Upstream Hexis artifact | Status | Why |
|---|---|---|
| `.claude/` templates | omitted | Claude Code-specific; duplicating them would add prompt bloat to Hermes. |
| Hexis `init/add/list/sync` CLI | omitted | Scaffolds Claude Code files and private sync conventions, not Hermes runtime behavior. |
| `post-edit-format.js` | omitted for now | Mutates files after edits; useful later only as a clearly opt-in formatter guardrail. |
| Example productivity skills | omitted | Should be ported only when they add Hermes-specific value. |

## Credit

Operating model, guard set, stuck-loop detector concept, and escalation
philosophy are from [Hexis](https://github.com/hexis-framework/hexis) by the
Hexis authors (MIT). This is an independent Hermes Agent port intended for a
community contribution path.
