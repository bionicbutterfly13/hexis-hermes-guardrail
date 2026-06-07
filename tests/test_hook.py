"""Universal hook contract tests — guardcore.hook.main.

Locks the cross-platform PreToolUse convergence: every supported platform pipes
its pending command as JSON on stdin and the hook answers with that platform's
exact deny shape (or an empty-object allow). These recorded-payload tests are the
guard against a future edit silently breaking one platform's wiring.

Hermeticity: HOME is pointed at a throwaway dir (so no real ~/.hexis-guardrails
config leaks in), GUARDCORE_CONFIG is cleared, and state I/O is redirected.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from guardcore import hook


def run_hook_raw(raw):
    """Feed *raw* string as stdin to hook.main(); return (rc, stdout)."""
    prev_stdin = sys.stdin
    sys.stdin = io.StringIO(raw)
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = hook.main()
    finally:
        sys.stdin = prev_stdin
    return rc, buf.getvalue()


def run_hook(payload):
    """Feed *payload* (dict) as stdin JSON to hook.main(); return (rc, stdout)."""
    return run_hook_raw(json.dumps(payload))


class HookContractTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="guardcore-hook-")
        self._saved = {k: os.environ.get(k)
                       for k in ("HOME", "GUARDCORE_CONFIG", "GUARDCORE_STATE_DIR")}
        os.environ["HOME"] = self._tmp                       # no real home config
        os.environ.pop("GUARDCORE_CONFIG", None)             # → DEFAULT_MODES
        os.environ["GUARDCORE_STATE_DIR"] = self._tmp        # redirect log writes

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- Claude Code / Codex (PreToolUse, tool_input.command) --------------- #
    def test_pretooluse_blocks_credential_read(self):
        rc, out = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                            "tool_input": {"command": "cat .env"}})
        self.assertEqual(rc, 0)
        d = json.loads(out)
        self.assertEqual(d["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(d["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        # the model-facing reason must actually carry the rule, not be empty
        self.assertIn("credential_read",
                      d["hookSpecificOutput"]["permissionDecisionReason"])

    def test_pretooluse_allows_benign(self):
        rc, out = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                            "tool_input": {"command": "ls -la"}})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "{}")

    def test_pretooluse_blocks_force_push_main(self):
        rc, out = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                            "tool_input": {"command": "git push --force origin main"}})
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_non_shell_tool_is_ignored(self):
        # A non-shell tool that happens to carry a "command" must NOT be inspected.
        rc, out = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Read",
                            "tool_input": {"command": "cat .env"}})
        self.assertEqual(out, "{}")

    def test_pretooluse_defensive_no_tool_name(self):
        # No tool_name but a command present → defensive inspect path still guards.
        rc, out = run_hook({"hook_event_name": "PreToolUse",
                            "tool_input": {"command": "cat .env"}})
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    # -- Cursor (beforeShellExecution, top-level command) ------------------- #
    def test_cursor_blocks_credential_read(self):
        rc, out = run_hook({"hook_event_name": "beforeShellExecution",
                            "command": "cat .env"})
        self.assertEqual(rc, 0)
        d = json.loads(out)
        self.assertEqual(d["permission"], "deny")
        self.assertIn("hexis:credential_read", d["agent_message"])
        self.assertIn("hexis:credential_read", d["user_message"])

    def test_cursor_allows_benign(self):
        rc, out = run_hook({"hook_event_name": "beforeShellExecution",
                            "command": "echo hi"})
        self.assertEqual(out, "{}")

    # -- fail-safe: never brick the agent loop ------------------------------ #
    def test_empty_stdin_allows(self):
        rc, out = run_hook_raw("")
        self.assertEqual((rc, out), (0, "{}"))

    def test_unparseable_stdin_allows(self):
        rc, out = run_hook_raw("not json {{{")
        self.assertEqual((rc, out), (0, "{}"))

    def test_missing_command_allows(self):
        rc, out = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                            "tool_input": {}})
        self.assertEqual(out, "{}")

    # -- config override is honored by the hook ----------------------------- #
    def test_config_override_disables_guard(self):
        cfg = os.path.join(self._tmp, "config.json")
        with open(cfg, "w") as fh:
            json.dump({"guards": {"credential_read": "off"}}, fh)
        os.environ["GUARDCORE_CONFIG"] = cfg
        rc, out = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                            "tool_input": {"command": "cat .env"}})
        self.assertEqual(out, "{}")

    # -- the load-bearing fail-safe: an internal fault must ALLOW, not crash -- #
    def test_internal_fault_fails_safe_to_allow(self):
        # If the rule engine raises on otherwise-valid input, the hook must not
        # propagate the exception (which would brick the agent loop) — it must
        # emit an allow. This is the whole reason Cursor is wired failClosed.
        with mock.patch.object(hook.guards, "evaluate",
                               side_effect=RuntimeError("boom")):
            rc, out = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                "tool_input": {"command": "cat .env"}})
        self.assertEqual((rc, out), (0, "{}"))

    # -- secrets must not leak through the hook's emitted deny --------------- #
    def test_inline_secret_redacted_in_emitted_deny(self):
        secret = "AKIAIOSFODNN7EXAMPLE"
        rc, out = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                            "tool_input": {"command": f"grep {secret} ~/.env"}})
        self.assertIn("deny", out)
        self.assertNotIn(secret, out)

    # -- Cursor session attribution (conversation_id) ----------------------- #
    def test_cursor_conversation_id_recorded_in_violation_log(self):
        rc, out = run_hook({"hook_event_name": "beforeShellExecution",
                            "command": "cat .env", "conversation_id": "conv-xyz"})
        self.assertEqual(json.loads(out)["permission"], "deny")
        log = Path(self._tmp) / "rule-violation-log.jsonl"
        rows = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
        cred = [r for r in rows if r.get("rule") == "credential_read"]
        self.assertTrue(cred and cred[-1].get("session_id") == "conv-xyz", rows)


if __name__ == "__main__":
    unittest.main()
