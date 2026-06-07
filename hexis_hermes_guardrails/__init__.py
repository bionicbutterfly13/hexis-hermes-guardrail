"""Hexis Hermes guardrails — multi-platform installer CLI.

Provides the ``hexis-hermes-guardrails`` console command that wires the
platform-agnostic core (the sibling ``guardcore`` package) into each AI coding
agent's pre-command hook: Claude Code, Codex, and Cursor (via a shared launcher
at ``~/.hexis-guardrails/``), and Hermes (via the ``hexis`` in-process adapter).
See ``cli.py`` for the commands and ``platforms.py`` for the per-platform logic.
"""

__version__ = "0.1.0"
