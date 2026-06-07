"""Interactive, multi-platform installer for the Hexis guardrails.

    hexis-hermes-guardrails install          # checkbox-pick platforms (detected ones pre-checked)
    hexis-hermes-guardrails install --all     # every supported platform
    hexis-hermes-guardrails install --platform claude-code,codex
    hexis-hermes-guardrails install --dry-run # show the plan, change nothing
    hexis-hermes-guardrails update            # re-sync the shared core to installed platforms
    hexis-hermes-guardrails uninstall [...]   # remove the guard (Hermes keeps state/)
    hexis-hermes-guardrails status            # what's detected / installed
    hexis-hermes-guardrails config            # print the Hermes enable block

Selection priority: --platform > --all > $HEXIS_PLATFORMS > interactive checkbox.
In a non-interactive shell with no selection, it errors with guidance (a security
control should never auto-install onto platforms you didn't choose).

Auto-update is OFF by default (a guard that blocks every shell command should not
silently change itself); use `update` to pull a new version when you choose to.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List

from . import platforms
from .platforms import REGISTRY, get, install_shared_core, maybe_remove_shared_core

_CONFIG_BLOCK = """\
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
"""

_VALID = {p.key for p in REGISTRY}


def _validate(keys: List[str]) -> List[str]:
    out, bad = [], []
    for k in keys:
        (out if k in _VALID else bad).append(k)
    if bad:
        print(f"Unknown platform(s): {', '.join(bad)}. "
              f"Valid: {', '.join(sorted(_VALID))}", file=sys.stderr)
        return []
    # de-dupe, preserve order
    seen, uniq = set(), []
    for k in out:
        if k not in seen:
            seen.add(k); uniq.append(k)
    return uniq


def _interactive_select(detected: List[str]) -> List[str]:
    try:
        import questionary
    except ImportError:
        print("Interactive mode needs `questionary` (pip install questionary), "
              "or pass --platform=... / --all.", file=sys.stderr)
        return []
    choices = []
    for p in REGISTRY:
        det = p.key in detected
        tags = []
        tags.append("detected" if det else "not detected")
        if p.is_installed():
            tags.append("installed")
        choices.append(questionary.Choice(
            title=f"{p.label}  ({', '.join(tags)})", value=p.key, checked=det))
    answer = questionary.checkbox(
        "Install Hexis guardrails on which platforms?  "
        "[space] toggle  [enter] confirm",
        choices=choices,
    ).ask()
    return answer or []


def _resolve_selection(args, detected: List[str]) -> List[str]:
    if getattr(args, "all", False):
        return [p.key for p in REGISTRY]
    if getattr(args, "platform", None):
        keys: List[str] = []
        for chunk in args.platform:
            keys += [c.strip() for c in chunk.split(",") if c.strip()]
        return _validate(keys)
    env = os.environ.get("HEXIS_PLATFORMS")
    if env:
        return _validate([c.strip() for c in env.split(",") if c.strip()])
    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not getattr(args, "no_input", False)
    if interactive:
        return _interactive_select(detected)
    print("No platforms selected. Pass --platform=<list> or --all "
          f"(valid: {', '.join(sorted(_VALID))}).", file=sys.stderr)
    return []


def cmd_install(args) -> int:
    detected = [p.key for p in REGISTRY if p.detect()]
    selection = _resolve_selection(args, detected)
    if not selection:
        return 1
    prefix = "DRY RUN — would install" if args.dry_run else "Installing"
    print(f"{prefix} Hexis guardrails on: {', '.join(selection)}\n")
    failures = []
    for key in selection:
        p = get(key)
        print(f"• {p.label}  ({p.note})")
        try:
            for a in p.install(args.dry_run):
                print(f"    {a}")
        except platforms.ConfigError as exc:
            print(f"    SKIPPED — {exc}")
            failures.append(key)
        print()
    if args.dry_run:
        print("(dry run — nothing changed)")
    else:
        print("Done. Verify with `hexis-hermes-guardrails status`.")
        if "hermes" in selection:
            print("\nHermes needs enabling in ~/.hermes/config.yaml:\n")
            print(_CONFIG_BLOCK)
    if failures:
        print(f"\nSkipped (fix the listed files, then re-run): {', '.join(failures)}",
              file=sys.stderr)
        return 1
    return 0


def cmd_update(args) -> int:
    installed = [p for p in REGISTRY if p.is_installed()]
    if not installed:
        print("Nothing installed to update.")
        return 0
    print(f"{'DRY RUN — ' if args.dry_run else ''}Updating shared core + "
          f"re-syncing: {', '.join(p.key for p in installed)}\n")
    install_shared_core(args.dry_run)
    for p in installed:
        try:
            for a in p.install(args.dry_run):
                print(f"  [{p.key}] {a}")
        except platforms.ConfigError as exc:
            print(f"  [{p.key}] SKIPPED — {exc}")
    print("\nDone." if not args.dry_run else "\n(dry run)")
    return 0


def cmd_uninstall(args) -> int:
    detected = [p.key for p in REGISTRY if p.is_installed()]
    selection = _resolve_selection(args, detected) if (args.all or args.platform or os.environ.get("HEXIS_PLATFORMS")) else detected
    if not selection:
        print("Nothing to uninstall.")
        return 0
    for key in selection:
        p = get(key)
        print(f"• {p.label}")
        try:
            for a in p.uninstall(args.dry_run):
                print(f"    {a}")
        except platforms.ConfigError as exc:
            print(f"    SKIPPED — {exc}")
    for a in maybe_remove_shared_core(args.dry_run):
        print(f"  {a}")
    return 0


def cmd_status(_args) -> int:
    print(f"{'Platform':<14} {'detected':<10} {'installed':<10} notes")
    print("-" * 72)
    for p in REGISTRY:
        print(f"{p.label:<14} {('yes' if p.detect() else 'no'):<10} "
              f"{('yes' if p.is_installed() else 'no'):<10} {p.note}")
    return 0


def cmd_config(_args) -> int:
    print(_CONFIG_BLOCK)
    return 0


def main(argv=None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # Affordance: a bare `--all` / `--platform x` (selection flags but no
    # subcommand) means `install`. Without this, argparse rejects the flags
    # because they live only on the install/uninstall subparsers.
    if raw and raw[0].startswith("-") and raw[0] not in ("-h", "--help"):
        raw = ["install"] + raw

    parser = argparse.ArgumentParser(
        prog="hexis-hermes-guardrails",
        description="Install Hexis command guardrails across your AI coding agents.",
    )
    sub = parser.add_subparsers(dest="command")

    def _add_selection_flags(sp):
        sp.add_argument("--platform", action="append",
                        help="platform(s) to target (repeatable or comma-list)")
        sp.add_argument("--all", action="store_true", help="all supported platforms")
        sp.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
        sp.add_argument("--no-input", action="store_true", help="never prompt (CI)")

    _add_selection_flags(sub.add_parser("install", help="install the guard on selected platforms"))
    up = sub.add_parser("update", help="re-sync the shared core to installed platforms")
    up.add_argument("--dry-run", action="store_true")
    _add_selection_flags(sub.add_parser("uninstall", help="remove the guard (Hermes keeps state/)"))
    sub.add_parser("status", help="show detected / installed platforms")
    sub.add_parser("config", help="print the Hermes enable block")

    args = parser.parse_args(raw)
    cmd = args.command or "install"
    # argparse with no subcommand: synthesize defaults for install
    if args.command is None:
        for attr, default in (("platform", None), ("all", False), ("dry_run", False), ("no_input", False)):
            setattr(args, attr, getattr(args, attr, default))

    return {
        "install": cmd_install,
        "update": cmd_update,
        "uninstall": cmd_uninstall,
        "status": cmd_status,
        "config": cmd_config,
    }[cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
