"""Installer tests — hexis_hermes_guardrails.platforms.

Drives the real per-platform install/uninstall logic against a throwaway HOME
(module globals are repointed in setUp), asserting each platform writes its
correct config shape, that the shared core + launcher land, that re-install is
idempotent, and that uninstall cleanly removes the guard. No real ~/.claude,
~/.codex, ~/.cursor, or ~/.hermes profile is touched.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from hexis_hermes_guardrails import platforms as P


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="hhg-installer-"))
        # Snapshot + repoint the module globals the install logic reads.
        self._saved = (P.HOME, P.SHARED_DIR, P.LAUNCHER)
        P.HOME = self._tmp
        P.SHARED_DIR = self._tmp / ".hexis-guardrails"
        P.LAUNCHER = P.SHARED_DIR / "bin" / "hexis-guard"
        self._prev_hermes = os.environ.pop("HERMES_HOME", None)  # → HOME/.hermes

    def tearDown(self):
        P.HOME, P.SHARED_DIR, P.LAUNCHER = self._saved
        if self._prev_hermes is not None:
            os.environ["HERMES_HOME"] = self._prev_hermes
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- shared core -------------------------------------------------------- #
    def test_shared_core_installs_launcher_and_guardcore(self):
        P.install_shared_core(dry_run=False)
        self.assertTrue((P.SHARED_DIR / "guardcore" / "hook.py").is_file())
        self.assertTrue(P.LAUNCHER.is_file())
        self.assertTrue(os.access(P.LAUNCHER, os.X_OK), "launcher must be executable")
        body = P.LAUNCHER.read_text()
        # The launcher must NOT interpolate the install path (the fail-open bug);
        # it resolves _run.py from its own location instead.
        self.assertNotIn(str(P.SHARED_DIR), body)
        self.assertIn('"$(dirname "$0")/_run.py"', body)
        run_py = (P.LAUNCHER.parent / "_run.py").read_text()
        self.assertIn("from guardcore import hook", run_py)
        self.assertNotIn(str(P.SHARED_DIR), run_py)  # resolved via __file__, not baked in

    def test_dry_run_changes_nothing(self):
        P.install_shared_core(dry_run=True)
        self.assertFalse(P.SHARED_DIR.exists())

    # -- Claude Code -------------------------------------------------------- #
    def test_claude_install_writes_pretooluse_bash(self):
        P._claude_install(dry_run=False)
        cfg = json.loads((self._tmp / ".claude" / "settings.json").read_text())
        entries = cfg["hooks"]["PreToolUse"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["matcher"], "Bash")
        self.assertEqual(entries[0]["hooks"][0]["command"], str(P.LAUNCHER))
        self.assertTrue(P._claude_installed())

    def test_claude_install_is_idempotent(self):
        P._claude_install(dry_run=False)
        P._claude_install(dry_run=False)
        cfg = json.loads((self._tmp / ".claude" / "settings.json").read_text())
        self.assertEqual(len(cfg["hooks"]["PreToolUse"]), 1)

    def test_claude_preserves_existing_unrelated_hooks(self):
        p = self._tmp / ".claude" / "settings.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Write", "hooks": [{"type": "command", "command": "/other/tool"}]}
        ]}}))
        P._claude_install(dry_run=False)
        cfg = json.loads(p.read_text())
        cmds = [h["command"] for e in cfg["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertIn("/other/tool", cmds)        # user's hook survived
        self.assertIn(str(P.LAUNCHER), cmds)      # ours was added

    def test_claude_uninstall_removes_only_our_hook(self):
        p = self._tmp / ".claude" / "settings.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Write", "hooks": [{"type": "command", "command": "/other/tool"}]}
        ]}}))
        P._claude_install(dry_run=False)
        P._claude_uninstall(dry_run=False)
        self.assertFalse(P._claude_installed())
        cfg = json.loads(p.read_text())
        cmds = [h["command"] for e in cfg["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertIn("/other/tool", cmds)          # user's hook preserved
        self.assertNotIn(str(P.LAUNCHER), cmds)     # ours gone

    # -- Codex -------------------------------------------------------------- #
    def test_codex_install_writes_anchored_matcher(self):
        P._codex_install(dry_run=False)
        cfg = json.loads((self._tmp / ".codex" / "hooks.json").read_text())
        entry = cfg["hooks"]["PreToolUse"][0]
        self.assertEqual(entry["matcher"], "^Bash$")
        self.assertEqual(entry["hooks"][0]["command"], str(P.LAUNCHER))

    # -- Cursor ------------------------------------------------------------- #
    def test_cursor_install_fails_closed(self):
        P._cursor_install(dry_run=False)
        cfg = json.loads((self._tmp / ".cursor" / "hooks.json").read_text())
        entry = cfg["hooks"]["beforeShellExecution"][0]
        self.assertEqual(entry["command"], str(P.LAUNCHER))
        self.assertIs(entry["failClosed"], True)
        self.assertEqual(cfg.get("version"), 1)

    def test_cursor_install_is_idempotent(self):
        P._cursor_install(dry_run=False)
        P._cursor_install(dry_run=False)
        cfg = json.loads((self._tmp / ".cursor" / "hooks.json").read_text())
        self.assertEqual(len(cfg["hooks"]["beforeShellExecution"]), 1)

    # -- Hermes ------------------------------------------------------------- #
    def test_hermes_install_lays_down_adapter_and_core(self):
        P._hermes_install(dry_run=False)
        dest = self._tmp / ".hermes" / "plugins" / "hexis"
        self.assertTrue((dest / "__init__.py").is_file())
        self.assertTrue((dest / "guardcore" / "hook.py").is_file())
        self.assertTrue(P._hermes_installed())

    def test_hermes_uninstall_preserves_state(self):
        P._hermes_install(dry_run=False)
        dest = self._tmp / ".hermes" / "plugins" / "hexis"
        (dest / "state").mkdir(parents=True, exist_ok=True)
        (dest / "state" / "rule-violation-log.jsonl").write_text('{"rule":"x"}\n')
        P._hermes_uninstall(dry_run=False)
        self.assertFalse((dest / "__init__.py").exists())
        self.assertFalse((dest / "guardcore").exists())
        self.assertTrue((dest / "state" / "rule-violation-log.jsonl").is_file())

    # -- uninstall coverage for the flat (Cursor) + nested (Codex) shapes --- #
    def test_cursor_uninstall_removes_our_hook(self):
        P._cursor_install(dry_run=False)
        self.assertTrue(P._cursor_installed())
        P._cursor_uninstall(dry_run=False)
        self.assertFalse(P._cursor_installed())

    def test_codex_uninstall_removes_our_hook(self):
        P._codex_install(dry_run=False)
        self.assertTrue(P._codex_installed())
        P._codex_uninstall(dry_run=False)
        self.assertFalse(P._codex_installed())

    def test_codex_install_is_idempotent(self):
        P._codex_install(dry_run=False)
        P._codex_install(dry_run=False)
        cfg = json.loads((self._tmp / ".codex" / "hooks.json").read_text())
        self.assertEqual(len(cfg["hooks"]["PreToolUse"]), 1)

    # -- dry-run writes nothing, on EVERY platform path --------------------- #
    def test_per_platform_dry_run_writes_nothing(self):
        for fn in (P._claude_install, P._codex_install,
                   P._cursor_install, P._hermes_install):
            fn(dry_run=True)
        self.assertFalse((self._tmp / ".claude" / "settings.json").exists())
        self.assertFalse((self._tmp / ".codex" / "hooks.json").exists())
        self.assertFalse((self._tmp / ".cursor" / "hooks.json").exists())
        self.assertFalse((self._tmp / ".hermes" / "plugins" / "hexis").exists())
        self.assertFalse(P.SHARED_DIR.exists())

    # -- malformed / wrong-shape configs must not be clobbered or crash ------ #
    def test_malformed_json_aborts_without_clobbering(self):
        p = self._tmp / ".claude" / "settings.json"
        p.parent.mkdir(parents=True)
        original = '{ "permissions": {}, }\n'  # trailing comma => invalid JSON
        p.write_text(original)
        with self.assertRaises(P.ConfigError):
            P._claude_install(dry_run=False)
        self.assertEqual(p.read_text(), original)   # untouched
        self.assertFalse(P.SHARED_DIR.exists())     # aborted before any write

    def test_detection_tolerates_malformed_config(self):
        # is_installed()/status must NEVER crash on a malformed config — they
        # just can't see our hook, so "not installed" is the safe answer.
        cdir = self._tmp / ".codex"; cdir.mkdir(parents=True)
        (cdir / "hooks.json").write_text("{ not valid json ")
        self.assertFalse(P._codex_installed())          # parse error tolerated
        ccdir = self._tmp / ".claude"; ccdir.mkdir(parents=True)
        (ccdir / "settings.json").write_text(json.dumps({"hooks": []}))  # wrong shape
        self.assertFalse(P._claude_installed())         # shape error tolerated

    def test_wrong_top_level_shape_raises(self):
        p = self._tmp / ".cursor" / "hooks.json"
        p.parent.mkdir(parents=True)
        p.write_text("[]")  # valid JSON, wrong shape (list, not object)
        with self.assertRaises(P.ConfigError):
            P._cursor_install(dry_run=False)

    def test_malformed_hooks_subtree_is_coerced(self):
        # A dict config whose hooks subtree is the wrong type must be repaired
        # in-place, not crash (AttributeError) the installer.
        p = self._tmp / ".claude" / "settings.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"hooks": {"PreToolUse": "oops-not-a-list"}}))
        P._claude_install(dry_run=False)  # must not raise
        cfg = json.loads(p.read_text())
        cmds = [h["command"] for e in cfg["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertIn(str(P.LAUNCHER), cmds)

    # -- shared core is cleaned up once the last hook platform is gone ------- #
    def test_shared_core_removed_only_when_last_hook_platform_gone(self):
        P._claude_install(dry_run=False)
        P._cursor_install(dry_run=False)
        self.assertTrue(P.SHARED_DIR.exists())
        P._claude_uninstall(dry_run=False)
        self.assertEqual(P.maybe_remove_shared_core(dry_run=False), [])  # cursor remains
        self.assertTrue(P.SHARED_DIR.exists())
        P._cursor_uninstall(dry_run=False)
        self.assertTrue(P.maybe_remove_shared_core(dry_run=False))       # now removed
        self.assertFalse(P.SHARED_DIR.exists())

    # -- the critical fix: launcher must work when HOME contains a quote ----- #
    def test_launcher_is_quote_safe_with_apostrophe_home(self):
        quoted = self._tmp / "o'brien" / ".hexis-guardrails"
        P.SHARED_DIR = quoted
        P.LAUNCHER = quoted / "bin" / "hexis-guard"
        P.install_shared_core(dry_run=False)
        syn = subprocess.run(["bash", "-n", str(P.LAUNCHER)],
                             capture_output=True, text=True)
        self.assertEqual(syn.returncode, 0, syn.stderr)  # syntactically valid
        env = dict(os.environ, HOME=str(self._tmp), GUARDCORE_STATE_DIR=str(self._tmp))
        deny = subprocess.run(
            ["bash", str(P.LAUNCHER)],
            input='{"hook_event_name":"PreToolUse","tool_name":"Bash",'
                  '"tool_input":{"command":"cat .env"}}',
            capture_output=True, text=True, env=env)
        self.assertEqual(deny.returncode, 0, deny.stderr)
        self.assertIn("deny", deny.stdout)  # NOT fail-open
        allow = subprocess.run(
            ["bash", str(P.LAUNCHER)],
            input='{"hook_event_name":"PreToolUse","tool_name":"Bash",'
                  '"tool_input":{"command":"ls -la"}}',
            capture_output=True, text=True, env=env)
        self.assertEqual(allow.stdout, "{}")

    # -- our backup must not clobber a user's own <config>.bak --------------- #
    def test_user_bak_file_is_preserved(self):
        p = self._tmp / ".claude" / "settings.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"permissions": {"allow": ["Bash"]}}))
        userbak = p.with_name(p.name + ".bak")
        userbak.write_text('{"USER_PRECIOUS": true}')
        P._claude_install(dry_run=False)  # changes config → triggers our backup
        self.assertEqual(json.loads(userbak.read_text()), {"USER_PRECIOUS": True})
        self.assertTrue(p.with_name(p.name + ".hexis.bak").is_file())  # ours, namespaced

    # -- launcher fail-safe: a broken core degrades to ALLOW, never a crash -- #
    def test_launcher_fails_safe_when_core_is_broken(self):
        P.install_shared_core(dry_run=False)
        (P.SHARED_DIR / "guardcore" / "hook.py").write_text("raise RuntimeError('x')\n")
        env = dict(os.environ, HOME=str(self._tmp), GUARDCORE_STATE_DIR=str(self._tmp))
        r = subprocess.run(
            ["bash", str(P.LAUNCHER)],
            input='{"hook_event_name":"PreToolUse","tool_name":"Bash",'
                  '"tool_input":{"command":"cat .env"}}',
            capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "{}")  # allow, not a traceback

    # -- a shadowing guardcore on PYTHONPATH must not hijack the guard ------- #
    def test_rogue_guardcore_on_pythonpath_does_not_hijack(self):
        P.install_shared_core(dry_run=False)
        rogue = self._tmp / "rogue" / "guardcore"
        rogue.mkdir(parents=True)
        (rogue / "__init__.py").write_text("")
        (rogue / "hook.py").write_text(
            "import sys\ndef main():\n    sys.stdout.write('{}')\n    return 0\n")
        env = dict(os.environ, HOME=str(self._tmp), GUARDCORE_STATE_DIR=str(self._tmp),
                   PYTHONPATH=str(self._tmp / "rogue"))
        r = subprocess.run(
            ["bash", str(P.LAUNCHER)],
            input='{"hook_event_name":"PreToolUse","tool_name":"Bash",'
                  '"tool_input":{"command":"cat .env"}}',
            capture_output=True, text=True, env=env)
        self.assertIn("deny", r.stdout)  # the REAL vendored guard won, not the rogue allow

    # -- cleanup must not delete the launcher under a still-wired config ----- #
    def test_shared_core_kept_when_corrupt_config_still_wires_launcher(self):
        P._claude_install(dry_run=False)
        P._codex_install(dry_run=False)
        self.assertTrue(P.SHARED_DIR.exists())
        codex = self._tmp / ".codex" / "hooks.json"
        codex.write_text(codex.read_text() + "  <<garbage")  # unparseable, launcher still present
        P._claude_uninstall(dry_run=False)
        self.assertFalse(P._codex_installed())            # lenient parse: reads as not-installed
        self.assertEqual(P.maybe_remove_shared_core(dry_run=False), [])  # but refuses to remove
        self.assertTrue(P.SHARED_DIR.exists())            # launcher preserved for still-wired codex

    # -- registry ----------------------------------------------------------- #
    def test_registry_lookup(self):
        self.assertEqual({p.key for p in P.REGISTRY},
                         {"claude-code", "codex", "cursor", "hermes"})
        self.assertIsNone(P.get("nope"))
        self.assertIsNotNone(P.get("cursor"))


if __name__ == "__main__":
    unittest.main()
