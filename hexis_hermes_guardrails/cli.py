"""Installer CLI for the Hexis Hermes guardrails plugin.

Usage::

    hexis-hermes-guardrails install      # copy plugin into ~/.hermes/plugins/hexis
    hexis-hermes-guardrails uninstall    # remove plugin code, keep state/
    hexis-hermes-guardrails uninstall --purge   # also remove state/
    hexis-hermes-guardrails config       # print the config block

Honors ``HERMES_HOME`` (defaults to ``~/.hermes``). The plugin files are copied
from the bundled ``hexis`` package, so this works after ``pip install`` without a
source checkout. Existing runtime ``state/`` is preserved on (re)install.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

# Plugin files copied into the Hermes profile. Kept in sync with the `hexis`
# package contents; missing optional files are skipped, not fatal.
_PLUGIN_FILES = [
    "__init__.py",
    "guards.py",
    "stuck.py",
    "violations.py",
    "plugin.yaml",
    "README.md",
    "SKILL.md",
]

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


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def _plugin_source() -> Path:
    """Locate the bundled plugin files (the installed ``hexis`` package dir)."""
    import hexis  # imported lazily so --help works even if something is off

    return Path(hexis.__file__).resolve().parent


def _install() -> int:
    src = _plugin_source()
    dest = _hermes_home() / "plugins" / "hexis"
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in _PLUGIN_FILES:
        s = src / name
        if s.exists():
            shutil.copy2(s, dest / name)
            copied += 1
    print(f"Installed hexis plugin ({copied} files) -> {dest}")
    print("(runtime state/ preserved if it already existed)\n")
    print("Next: enable it in ~/.hermes/config.yaml\n")
    print(_CONFIG_BLOCK)
    return 0


def _uninstall(purge: bool) -> int:
    dest = _hermes_home() / "plugins" / "hexis"
    # Safety: only ever operate on a path that ends in plugins/hexis.
    if dest.name != "hexis" or dest.parent.name != "plugins":
        print(f"Refusing to operate on unexpected path: {dest}", file=sys.stderr)
        return 1
    if not dest.exists():
        print(f"Nothing to uninstall: {dest} not present")
        return 0
    if purge:
        shutil.rmtree(dest)
        print(f"Purged {dest} (including state/).")
    else:
        for name in _PLUGIN_FILES:
            (dest / name).unlink(missing_ok=True)
        shutil.rmtree(dest / "__pycache__", ignore_errors=True)
        print(f"Removed plugin code from {dest}; preserved state/ (violation history).")
    print("Remember to remove 'hexis' from plugins.enabled in your config.yaml.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="hexis-hermes-guardrails",
        description="Install the Hexis guardrails plugin into a Hermes Agent profile.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("install", help="Copy the plugin into ~/.hermes/plugins/hexis and print the config block.")
    un = sub.add_parser("uninstall", help="Remove the installed plugin (preserves state/ unless --purge).")
    un.add_argument("--purge", action="store_true", help="Also delete state/ (violation history).")
    sub.add_parser("config", help="Print the config block that enables the plugin.")

    args = parser.parse_args(argv)
    if args.command == "install":
        return _install()
    if args.command == "uninstall":
        return _uninstall(args.purge)
    if args.command == "config":
        print(_CONFIG_BLOCK)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
