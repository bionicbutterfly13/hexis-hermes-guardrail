"""Platform registry + per-platform install logic for the Hexis guardrails.

Each platform knows how to (1) detect whether it's present, (2) report whether
the guard is already installed, and (3) install / uninstall a pre-command guard.

The **hook-based** platforms (Claude Code, Codex, Cursor) share ONE installed
core at ``~/.hexis-guardrails/`` plus a launcher script they all point at, so a
single core update covers them all. **Hermes** is a native directory plugin and
uses its own ``~/.hermes/plugins/hexis/`` path.

All config writes are idempotent JSON merges — we never clobber a user's other
hooks; we add our entry only if our launcher isn't already wired in.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

HOME = Path.home()

# Shared install location for the hook platforms.
SHARED_DIR = HOME / ".hexis-guardrails"
LAUNCHER = SHARED_DIR / "bin" / "hexis-guard"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _guardcore_src() -> Path:
    import guardcore

    return Path(guardcore.__file__).resolve().parent


def _hexis_src() -> Path:
    import hexis

    return Path(hexis.__file__).resolve().parent


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(HOME / ".hermes")))


def _which(name: str) -> bool:
    return shutil.which(name) is not None


class ConfigError(Exception):
    """A target config file exists but cannot be safely merged into."""


def _load_json(p: Path) -> dict:
    """Lenient read for DETECTION: ``{}`` if absent, unparseable, or wrong-shape.

    Read-only callers (is_installed/status) must never crash on a malformed
    config — they just can't see our hook, so "not installed" is the safe answer.
    The write path uses ``_load_json_strict`` so it refuses to clobber instead.
    """
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_json_strict(p: Path) -> dict:
    """Write-path read: ``{}`` if absent, else a dict — or raise ConfigError.

    Raises if the file EXISTS but is unparseable or is not a JSON object. We must
    never treat "present but malformed" the same as "absent", because doing so
    would silently overwrite (clobber) the user's real config.
    """
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ConfigError(
            f"{p} exists but is not valid JSON ({exc}). "
            "Fix or remove it, then re-run — refusing to overwrite it."
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(
            f"{p} is not a JSON object (got {type(data).__name__}). "
            "Refusing to overwrite it."
        )
    return data


def _write_json(p: Path, data: dict, dry_run: bool) -> None:
    if dry_run:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    # Back up an existing file before overwriting (only reached when a merge
    # actually changed something) — a security control must not lose your config.
    # Use a namespaced suffix so we never clobber a user's own <config>.bak.
    if p.is_file():
        shutil.copy2(p, p.with_name(p.name + ".hexis.bak"))
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# Bootstrap script run by the launcher. It resolves the shared-core dir from its
# OWN location (__file__), so NO install path is ever interpolated into a shell
# or `python -c` string. That interpolation was a fail-open hazard: a home dir
# containing a quote/space would produce a broken launcher and silently disable
# the guard (Claude/Codex see a failed hook as "allow").
_RUN_PY = '''\
"""Hexis guardrails bootstrap — invoked by the `hexis-guard` launcher.

Sits at <shared>/bin/_run.py; its grandparent is the shared-core dir holding
guardcore/. Resolved from __file__ so no path is interpolated anywhere.
"""
import os
import sys

_SHARED = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Force the vendored core to the FRONT even if _SHARED is already on sys.path,
# so a shadowing `guardcore` elsewhere on the path can't hijack the guard.
sys.path = [_SHARED] + [p for p in sys.path if p != _SHARED]

try:
    from guardcore import hook
    # Be certain we loaded OUR vendored engine, not a path shadow.
    if not os.path.abspath(hook.__file__).startswith(_SHARED):
        raise ImportError("guardcore resolved outside the shared core")
except Exception:
    # A broken/partial/shadowed core must DEGRADE TO ALLOW, never crash the loop.
    sys.stdout.write("{}")
    sys.exit(0)

sys.exit(hook.main())
'''

# Quote-safe: `"$0"` and the command substitution are double-quoted, so a home
# path with a single quote or a space is preserved intact.
_LAUNCHER_SH = '''\
#!/usr/bin/env bash
# Hexis guardrails launcher — shared by all hook-based platforms.
exec python3 "$(dirname "$0")/_run.py"
'''


def install_shared_core(dry_run: bool = False) -> List[str]:
    """Install/refresh the shared guardcore + launcher used by hook platforms."""
    actions = [f"sync core      -> {SHARED_DIR / 'guardcore'}",
               f"write launcher -> {LAUNCHER}"]
    if dry_run:
        return actions
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    (SHARED_DIR / "bin").mkdir(parents=True, exist_ok=True)
    dest_core = SHARED_DIR / "guardcore"
    if dest_core.exists():
        shutil.rmtree(dest_core)
    shutil.copytree(_guardcore_src(), dest_core,
                    ignore=shutil.ignore_patterns("__pycache__"))
    (LAUNCHER.parent / "_run.py").write_text(_RUN_PY, encoding="utf-8")
    LAUNCHER.write_text(_LAUNCHER_SH, encoding="utf-8")
    LAUNCHER.chmod(LAUNCHER.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return actions


def _merge_command_hook(cfg: dict, event: str, entry_extra: dict) -> bool:
    """Add a {matcher?, hooks:[{type:command, command:LAUNCHER}]} entry under
    cfg['hooks'][event] if our launcher isn't already wired. Returns True if
    changed. ``entry_extra`` carries event-specific fields (e.g. matcher)."""
    hooks = _coerce_dict(cfg, "hooks")
    arr = _coerce_list(hooks, event)
    launcher = str(LAUNCHER)
    for item in arr:
        if not isinstance(item, dict):
            continue
        for h in (item.get("hooks") or []):
            if isinstance(h, dict) and h.get("command") == launcher:
                return False  # already installed
    entry = dict(entry_extra)
    entry["hooks"] = [{"type": "command", "command": launcher}]
    arr.append(entry)
    return True


def _coerce_dict(parent: dict, key: str) -> dict:
    """Return parent[key] as a dict, replacing a non-dict (malformed) value."""
    v = parent.get(key)
    if not isinstance(v, dict):
        v = parent[key] = {}
    return v


def _coerce_list(parent: dict, key: str) -> list:
    """Return parent[key] as a list, replacing a non-list (malformed) value."""
    v = parent.get(key)
    if not isinstance(v, list):
        v = parent[key] = []
    return v


def _merge_flat_hook(cfg: dict, event: str, extra: dict) -> bool:
    """Cursor-style: cfg['hooks'][event] is a list of {command, ...} entries."""
    cfg.setdefault("version", 1)
    hooks = _coerce_dict(cfg, "hooks")
    arr = _coerce_list(hooks, event)
    launcher = str(LAUNCHER)
    for item in arr:
        if isinstance(item, dict) and item.get("command") == launcher:
            return False
    entry = {"command": launcher}
    entry.update(extra)
    arr.append(entry)
    return True


def _remove_launcher_hooks(cfg: dict) -> bool:
    """Strip any hook entry pointing at our launcher. Returns True if changed."""
    launcher = str(LAUNCHER)
    changed = False
    hooks = cfg.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for event, arr in list(hooks.items()):
        if not isinstance(arr, list):
            continue
        kept = []
        for item in arr:
            if isinstance(item, dict) and item.get("command") == launcher:
                changed = True
                continue
            inner = item.get("hooks") if isinstance(item, dict) else None
            if isinstance(inner, list):
                new_inner = [h for h in inner if not (isinstance(h, dict) and h.get("command") == launcher)]
                if len(new_inner) != len(inner):
                    changed = True
                    if not new_inner:
                        continue  # drop the now-empty matcher entry
                    item = dict(item, hooks=new_inner)
            kept.append(item)
        cfg["hooks"][event] = kept
    return changed


def _has_launcher(cfg: dict, event: str, nested: bool) -> bool:
    """Detect our launcher under cfg['hooks'][event], tolerant of any shape."""
    hooks = cfg.get("hooks")
    if not isinstance(hooks, dict):
        return False
    arr = hooks.get(event)
    if not isinstance(arr, list):
        return False
    launcher = str(LAUNCHER)
    for item in arr:
        if not isinstance(item, dict):
            continue
        if nested:
            for h in (item.get("hooks") or []):
                if isinstance(h, dict) and h.get("command") == launcher:
                    return True
        elif item.get("command") == launcher:
            return True
    return False


# --------------------------------------------------------------------------- #
# Platform definitions
# --------------------------------------------------------------------------- #
@dataclass
class Platform:
    key: str
    label: str
    detect: Callable[[], bool]
    is_installed: Callable[[], bool]
    install: Callable[[bool], List[str]]
    uninstall: Callable[[bool], List[str]]
    note: str = ""


# ---- Claude Code (settings.json PreToolUse hook) --------------------------- #
def _claude_settings() -> Path:
    return HOME / ".claude" / "settings.json"


def _claude_detect() -> bool:
    return (HOME / ".claude").is_dir() or _which("claude")


def _claude_installed() -> bool:
    return _has_launcher(_load_json(_claude_settings()), "PreToolUse", nested=True)


def _claude_install(dry_run: bool) -> List[str]:
    p = _claude_settings()
    cfg = _load_json_strict(p)  # may raise ConfigError → abort before side effects
    acts = install_shared_core(dry_run)
    if _merge_command_hook(cfg, "PreToolUse", {"matcher": "Bash"}):
        _write_json(p, cfg, dry_run)
        acts.append(f"wire PreToolUse(Bash) -> {p}")
    else:
        acts.append(f"already wired in {p}")
    return acts


def _claude_uninstall(dry_run: bool) -> List[str]:
    p = _claude_settings()
    cfg = _load_json(p)
    if _remove_launcher_hooks(cfg):
        _write_json(p, cfg, dry_run)
        return [f"remove guard hook from {p}"]
    return [f"no guard hook in {p}"]


# ---- Codex CLI (~/.codex/hooks.json PreToolUse) ---------------------------- #
def _codex_hooks() -> Path:
    return HOME / ".codex" / "hooks.json"


def _codex_detect() -> bool:
    return (HOME / ".codex").is_dir() or _which("codex")


def _codex_installed() -> bool:
    return _has_launcher(_load_json(_codex_hooks()), "PreToolUse", nested=True)


def _codex_install(dry_run: bool) -> List[str]:
    p = _codex_hooks()
    cfg = _load_json_strict(p)  # may raise ConfigError → abort before side effects
    acts = install_shared_core(dry_run)
    if _merge_command_hook(cfg, "PreToolUse", {"matcher": "^Bash$"}):
        _write_json(p, cfg, dry_run)
        acts.append(f"wire PreToolUse(^Bash$) -> {p}")
    else:
        acts.append(f"already wired in {p}")
    acts.append("NOTE: ensure [features] hooks = true in ~/.codex/config.toml; "
                "first run will prompt to trust the hook.")
    return acts


def _codex_uninstall(dry_run: bool) -> List[str]:
    p = _codex_hooks()
    cfg = _load_json(p)
    if _remove_launcher_hooks(cfg):
        _write_json(p, cfg, dry_run)
        return [f"remove guard hook from {p}"]
    return [f"no guard hook in {p}"]


# ---- Cursor (~/.cursor/hooks.json beforeShellExecution) -------------------- #
def _cursor_hooks() -> Path:
    return HOME / ".cursor" / "hooks.json"


def _cursor_detect() -> bool:
    return (HOME / ".cursor").is_dir() or _which("cursor") or _which("cursor-agent")


def _cursor_installed() -> bool:
    return _has_launcher(_load_json(_cursor_hooks()), "beforeShellExecution", nested=False)


def _cursor_install(dry_run: bool) -> List[str]:
    p = _cursor_hooks()
    cfg = _load_json_strict(p)  # may raise ConfigError → abort before side effects
    acts = install_shared_core(dry_run)
    # failClosed:true — Cursor defaults to fail-OPEN; a guard must fail closed.
    if _merge_flat_hook(cfg, "beforeShellExecution", {"timeout": 30, "failClosed": True}):
        _write_json(p, cfg, dry_run)
        acts.append(f"wire beforeShellExecution (failClosed) -> {p}")
    else:
        acts.append(f"already wired in {p}")
    return acts


def _cursor_uninstall(dry_run: bool) -> List[str]:
    p = _cursor_hooks()
    cfg = _load_json(p)
    if _remove_launcher_hooks(cfg):
        _write_json(p, cfg, dry_run)
        return [f"remove guard hook from {p}"]
    return [f"no guard hook in {p}"]


# ---- Hermes (native directory plugin) -------------------------------------- #
_HERMES_ADAPTER_FILES = ["__init__.py", "plugin.yaml", "README.md", "SKILL.md"]


def _hermes_dest() -> Path:
    return hermes_home() / "plugins" / "hexis"


def _hermes_detect() -> bool:
    return hermes_home().is_dir() or _which("hermes")


def _hermes_installed() -> bool:
    d = _hermes_dest()
    return (d / "__init__.py").is_file() and (d / "guardcore").is_dir()


def _hermes_install(dry_run: bool) -> List[str]:
    dest = _hermes_dest()
    acts = [f"install adapter + core -> {dest}"]
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
        src = _hexis_src()
        for f in _HERMES_ADAPTER_FILES:
            s = src / f
            if s.exists():
                shutil.copy2(s, dest / f)
        core_dest = dest / "guardcore"
        if core_dest.exists():
            shutil.rmtree(core_dest)
        shutil.copytree(_guardcore_src(), core_dest,
                        ignore=shutil.ignore_patterns("__pycache__"))
        for legacy in ("guards.py", "stuck.py", "violations.py"):
            (dest / legacy).unlink(missing_ok=True)
    acts.append("NOTE: add 'hexis' to plugins.enabled in ~/.hermes/config.yaml "
                "(run `hexis-hermes-guardrails config`).")
    return acts


def _hermes_uninstall(dry_run: bool) -> List[str]:
    dest = _hermes_dest()
    if dest.name != "hexis" or dest.parent.name != "plugins":
        return [f"refusing unexpected path: {dest}"]
    if not dest.exists():
        return [f"not installed: {dest}"]
    if not dry_run:
        for f in _HERMES_ADAPTER_FILES:
            (dest / f).unlink(missing_ok=True)
        shutil.rmtree(dest / "guardcore", ignore_errors=True)
        shutil.rmtree(dest / "__pycache__", ignore_errors=True)
    return [f"remove adapter + core from {dest} (state/ preserved)"]


REGISTRY = [
    Platform("claude-code", "Claude Code", _claude_detect, _claude_installed,
             _claude_install, _claude_uninstall,
             note="PreToolUse hook in ~/.claude/settings.json"),
    Platform("codex", "Codex CLI", _codex_detect, _codex_installed,
             _codex_install, _codex_uninstall,
             note="PreToolUse hook in ~/.codex/hooks.json (needs features.hooks)"),
    Platform("cursor", "Cursor", _cursor_detect, _cursor_installed,
             _cursor_install, _cursor_uninstall,
             note="beforeShellExecution hook in ~/.cursor/hooks.json (failClosed)"),
    Platform("hermes", "Hermes", _hermes_detect, _hermes_installed,
             _hermes_install, _hermes_uninstall,
             note="native plugin in ~/.hermes/plugins/hexis"),
]


def get(key: str) -> Optional[Platform]:
    for p in REGISTRY:
        if p.key == key:
            return p
    return None


_HOOK_PLATFORM_KEYS = ("claude-code", "codex", "cursor")


def _launcher_referenced_in_configs() -> bool:
    """True if any hook config's RAW TEXT still mentions the launcher.

    Textual, not JSON-parsed: a corrupt-but-still-wired config (one we couldn't
    cleanly rewrite on uninstall) must still keep the shared core alive, or we'd
    delete the launcher out from under a hook that still points at it (fail-open).
    """
    launcher = str(LAUNCHER)
    for getter in (_claude_settings, _codex_hooks, _cursor_hooks):
        p = getter()
        try:
            if p.is_file() and launcher in p.read_text(encoding="utf-8"):
                return True
        except OSError:
            return True  # unreadable → be conservative, keep the core
    return False


def maybe_remove_shared_core(dry_run: bool = False) -> List[str]:
    """Remove the shared core dir once no hook platform references it anymore.

    Called after uninstall. The shared launcher + core is only useful while a
    hook platform points at it; leaving it behind orphans an executable in HOME.
    Skipped while any hook platform is still installed OR any config still
    textually references the launcher (they share the dir).
    """
    if any(get(k).is_installed() for k in _HOOK_PLATFORM_KEYS):
        return []
    if _launcher_referenced_in_configs():
        return []
    if not SHARED_DIR.exists():
        return []
    if SHARED_DIR.name != ".hexis-guardrails":  # path-sanity guard before rmtree
        return [f"refusing to remove unexpected shared dir: {SHARED_DIR}"]
    if not dry_run:
        shutil.rmtree(SHARED_DIR, ignore_errors=True)
    return [f"remove shared core -> {SHARED_DIR}"]
