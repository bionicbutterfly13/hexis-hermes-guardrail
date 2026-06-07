"""Core rule tests — guardcore.guards.evaluate.

These lock the security-relevant decisions of the pure core: which commands
block, which only warn, how config modes (off/warn/block) override defaults, and
that a block is a pure function of (command, mode) that still fires when state
I/O is redirected. All violation logging is sent to a throwaway state dir via
$GUARDCORE_STATE_DIR so the real ~/.hexis-guardrails profile is never touched.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from guardcore import guards


class GuardEvalTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="guardcore-test-")
        self._prev = os.environ.get("GUARDCORE_STATE_DIR")
        os.environ["GUARDCORE_STATE_DIR"] = self._tmp

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("GUARDCORE_STATE_DIR", None)
        else:
            os.environ["GUARDCORE_STATE_DIR"] = self._prev
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- block-mode guards (default: block) --------------------------------- #
    def test_credential_read_blocks(self):
        d = guards.evaluate("cat .env", {})
        self.assertIsInstance(d, dict)
        self.assertEqual(d["action"], "block")
        self.assertIn("credential_read", d["message"])

    def test_force_push_main_blocks_long_flag(self):
        d = guards.evaluate("git push --force origin main", {})
        self.assertIsInstance(d, dict)
        self.assertEqual(d["action"], "block")
        self.assertIn("force_push_main", d["message"])

    def test_force_push_main_blocks_short_flag(self):
        d = guards.evaluate("git push -f origin master", {})
        self.assertEqual((d or {}).get("action"), "block")

    def test_force_push_to_feature_branch_allowed(self):
        self.assertIsNone(guards.evaluate("git push --force origin feature/x", {}))

    # -- warn-mode guards (default: warn → no block) ------------------------ #
    def test_rm_rf_warns_does_not_block(self):
        self.assertIsNone(guards.evaluate("rm -rf /tmp/scratch", {}))

    def test_unscoped_search_warns_does_not_block(self):
        self.assertIsNone(guards.evaluate("grep -r TODO ~", {}))

    # -- benign / negative controls ----------------------------------------- #
    def test_benign_command_allowed(self):
        self.assertIsNone(guards.evaluate("ls -la", {}))

    def test_empty_command_allowed(self):
        self.assertIsNone(guards.evaluate("", {}))

    # -- mode overrides ----------------------------------------------------- #
    def test_off_disables_a_block_guard(self):
        self.assertIsNone(guards.evaluate("cat .env", {"credential_read": "off"}))

    def test_warn_demotes_a_block_guard(self):
        self.assertIsNone(guards.evaluate("cat .env", {"credential_read": "warn"}))

    def test_block_escalates_a_warn_guard(self):
        d = guards.evaluate("rm -rf /tmp/scratch", {"rm_rf": "block"})
        self.assertEqual((d or {}).get("action"), "block")

    def test_invalid_mode_falls_back_to_guard_default(self):
        # A config typo must NOT silently demote a block-default guard.
        d = guards.evaluate("cat .env", {"credential_read": "bogus"})
        self.assertEqual((d or {}).get("action"), "block")

    # -- evasion shapes the heuristics still catch -------------------------- #
    def test_sudo_wrapper_still_caught(self):
        d = guards.evaluate("sudo cat ~/.aws/credentials", {})
        self.assertEqual((d or {}).get("action"), "block")

    def test_bash_dash_c_nested_still_caught(self):
        d = guards.evaluate('bash -c "cat .env"', {})
        self.assertEqual((d or {}).get("action"), "block")

    def test_second_segment_of_chain_caught(self):
        d = guards.evaluate("echo hi && cat secrets.pem", {})
        self.assertEqual((d or {}).get("action"), "block")

    # -- durable violation log (fail-safe: decision is independent of I/O) --- #
    def test_block_writes_durable_violation_row(self):
        guards.evaluate("cat .env", {})
        log = Path(self._tmp) / "rule-violation-log.jsonl"
        self.assertTrue(log.is_file(), f"missing violation log: {log}")
        rows = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
        self.assertTrue(any(r.get("rule") == "credential_read" for r in rows), rows)

    def test_secret_is_redacted_in_message(self):
        # An inline secret in a guarded command must not leak into the message.
        d = guards.evaluate("grep AKIAIOSFODNN7EXAMPLE ~/.env", {})
        self.assertEqual((d or {}).get("action"), "block")
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", d["message"])


if __name__ == "__main__":
    unittest.main()
