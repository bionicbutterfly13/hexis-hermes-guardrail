---
name: enforce
description: >-
  Hexis enforcement-escalation workflow. Use when a recurring mistake keeps
  happening despite existing rules, or when reviewing the hexis violation log to
  decide what should graduate from soft guidance to a hard gate. Classifies a
  repeat failure's root cause, routes it to the right knowledge layer, and
  applies Hexis' two-strike rule for promoting a `warn` guard to `block`.
user_invocable: true
---

# hexis:enforce - Enforcement Escalation

This skill is the judgment half of the Hexis port. The plugin's code handles
mechanical detection: command guardrails, stuck-loop guardrails, and violation
logging. This skill handles curation: deciding when a repeated mistake should
become an enforced rule, and where each piece of knowledge belongs.

## The Escalation Ladder

```text
observation -> soft rule -> memory/skill reminder -> violation log
            -> repeat violation -> hard gate (guard set to "block")
```

A rule should only climb to a hard gate when it is repeated despite documented
guidance, binary enough to validate mechanically, and high-impact enough to
justify enforcement. Most rules should never become gates.

## When To Use

- A mistake recurred even though a rule or memory already covered it.
- The hexis violation log shows the same `rule` logged 2+ times.
- You are doing a periodic review of agent self-correction.

## Inputs

The violation log lives under the active profile's Hermes home:

- `~/.hermes/plugins/hexis/state/rule-violation-log.jsonl`
- `~/.hermes/plugins/hexis/state/rule-violation-log.md`
- `~/.hermes/plugins/hexis/state/tool-call-log.jsonl`

## Workflow

### Step 1 - Read The Log

Read the violation log. Group by `rule`. For each rule, note how many times it
has fired and in what modes (`warn` vs `block`). A rule with 2+ `warn` entries
is a graduation candidate.

### Step 2 - Classify The Root Cause

Ask these in order; the first "yes" is the root cause and dictates the fix (the
count does not):

1. Is the rule itself unclear or ambiguous? -> rewrite the rule; do NOT escalate yet.
2. Does it conflict with another instruction? -> resolve the conflict; do NOT escalate.
3. Are legitimate exceptions common? -> do NOT gate (a gate is binary).
4. Was it an uncovered edge case? -> broaden the rule's scope.
5. Otherwise — was it forgotten under context pressure despite being clear? -> graduation candidate (continue to Step 4).

### Step 3 - Route To The Right Layer

Send the lesson to exactly ONE home. Ask in order:

1. Is it "must not happen", binary, and high-impact? -> a hexis guard set to `block` (Step 4).
2. Is it a reusable how-to or procedure? -> a Hermes skill or project solution note.
3. Is it a durable user/project fact that outlives this work? -> Hermes memory.
4. Is it an "X breaks when Y" gotcha? -> project notes or a memory gotcha.

Avoid stuffing imperatives into always-loaded prompts; that is the prompt-bloat
anti-pattern Hexis warns against.

### Step 4 - Graduate A Guard

If and only if Step 2 says context pressure / must not happen, and the rule has
fired 2+ times, promote it:

1. In `config.yaml`, set `plugins.entries.hexis.guards.<key>: block`.
2. Append a row to the violation log describing why.
3. Record the rationale in the project's normal decision record, if one exists.

High-severity rules such as data loss or credential exposure may be gated after
a single occurrence.

### Step 5 - Prune

Remove rules that stopped firing and were never real. Demote any `block` guard
that creates frequent legitimate-use friction back to `warn`. Enforcement should
stay lean.

## Rationalizations to Reject

Catch the skip-reasoning at the moment it occurs:

- "It was only a one-off." -> Log it now. You cannot tell a one-off from a
  pattern's first strike without the record. The log is how you find out.
- "It only happened twice - not worth a gate." -> Two logged strikes IS the
  graduation trigger for a context-pressure / must-not-happen rule. Do not
  re-litigate the threshold per incident.
- "I'll log it after I finish the task." -> You won't. The session ends and the
  violation is forgotten. Log at the moment of failure.
- "The rule is basically working." -> If it is in the log, it already failed at
  least once. Classify the root cause instead of defending the rule.
- "Blocking would be annoying." -> That is why warn-first exists. Graduate only
  the binary, high-impact, repeated rules - but do not refuse to graduate a
  qualifying rule because a block feels heavy. Friction from a false block is
  fixed by demoting it (Step 5), not by never gating.

## Output

A short summary: reviewed rules, counts, root-cause classification, what was
routed where, and any guard promoted/demoted, including the exact `config.yaml`
change if a guard graduated.

## Notes

- Guard keys: `rm_rf`, `unscoped_search`, `credential_read`,
  `force_push_main`, `pkg_manager_mismatch`.
- Guard modes: `warn` | `block` | `off`.
- This skill never edits Hermes core. The only config it touches is the
  user-owned active Hermes profile config.
