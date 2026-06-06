# Hexis Hermes Guardrails

Metacognitive guardrails for **Hermes Agent**, ported from the
[Hexis framework](https://github.com/hexis-framework/hexis). An update-safe Hermes
plugin that turns repeated agent mistakes into enforceable behavior:

```text
observation → soft rule → reminder → violation log → repeat violation → hard gate
```

It lives entirely under `~/.hermes/plugins/hexis/` and never patches Hermes core.

## What it provides

| Guardrail | What it does (heuristic) | Default |
|---|---|---|
| Credential reads | Flags common reads of `.env`/`.pem`/SSH/`.netrc`/cloud creds by common readers | `block` |
| Force-push to `main`/`master` | Flags `--force`/`-f`/`--force-with-lease`/`+ref` to main/master | `block` |
| `rm -rf` | Flags destructive `rm` with `-r`/`-f` | `warn` |
| Unscoped search | Flags `grep`/`rg`/`find`/`fd` rooted at the home **root** | `warn` |
| Package-manager mismatch | Warns when `npm` mutates a pnpm/yarn/bun project | `warn` |
| Stuck-loop detection | Repeated calls, repeated errors, A-B-A-B oscillation | `warn/log` |

Guards fire **only** on the `terminal` tool. They are heuristic defense-in-depth,
**not a security boundary** — Hermes core is the real credential/approval gate.
Full reference: [`hexis/README.md`](hexis/README.md).

## Requirements

You need a working **Hermes Agent** install (this is a Hermes plugin, not
standalone software). The plugin requires Python 3.9+.

## Install

**With pip** (once published to PyPI):

```bash
pip install hexis-hermes-guardrails
hexis-hermes-guardrails install      # copies the plugin into ~/.hermes/plugins/hexis/
```

**From a checkout:**

```bash
scripts/install.sh                   # same copy, preserves any existing state/
```

Either way, then enable it in `~/.hermes/config.yaml`:

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

`hexis-hermes-guardrails config` prints that block any time.

## Uninstall

```bash
hexis-hermes-guardrails uninstall    # or: scripts/uninstall.sh
```

Removes the plugin code but keeps your violation history (`state/`). Add `--purge`
to remove the state too. Remember to drop `hexis` from `plugins.enabled`.

## Verify

Two complementary checks:

- **`scripts/smoke-test.sh`** — *hermetic*. Installs into a throwaway `HERMES_HOME`,
  compiles the plugin, checks hook + skill registration and representative
  `block`/`warn` behavior, then uninstalls. Runs anywhere; never touches your real
  profile. Good for CI.
- **`python3 scripts/verify_live_runtime.py`** — *integration*. Drives a **live**
  Hermes runtime (real plugin loader, hook registry, dispatch, config, violation
  log) and confirms the guard contract against running Hermes code. SKIPs cleanly
  if Hermes isn't installed.

## Layout

```text
hexis/                     the plugin (the actual code — this is what installs)
  __init__.py              hook registration (4 hooks + the enforce skill)
  guards.py                command guards (credential/force-push/rm/search/pkg)
  stuck.py                 stuck-loop detector
  violations.py            durable violation + tool-call logs
  plugin.yaml, README.md, SKILL.md
hexis_hermes_guardrails/   pip installer CLI (`hexis-hermes-guardrails install`)
scripts/
  install.sh / uninstall.sh
  smoke-test.sh            hermetic install/uninstall test
  verify_live_runtime.py   live-runtime integration validation
pyproject.toml             packaging
LICENSE                    MIT
```

## License

MIT — see [`LICENSE`](LICENSE). Independent port of [Hexis](https://github.com/hexis-framework/hexis) (MIT); see the Credit section of `hexis/README.md`.
