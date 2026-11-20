---
name: Jev
description: Ask TypeSafe's Jev a typed question when you need a judgment rather than generation - is this spam, which of these options, how severe, is this claim supported. Use for classification, routing, extraction-by-selection, re-ranking, and any check that would otherwise be a brittle regex, keyword list, or prompt-and-parse step.
---

# Jev

`jev` is on PATH and talks to TypeSafe. It returns typed probabilities, so you
decide on numbers instead of parsing prose.

Load the `typesafe-ai` skill before writing anything non-trivial: it covers how to
split a judgment into atomic questions, structure state, and set thresholds.

## Commands

```bash
jev models                                   # available models
jev noul "Is this message a refund request?" --state-file ticket.json
jev noul "..." --state-file t.json --criteria "They want money back" "They ask for information only"
jev choice "Which product is this about?" --state-file t.json --criteria '{"proxy":"..."}'
jev score "How severe is the bug?" --state-file t.json --criteria "Cosmetic" "Broken feature" "Data loss"
jev ask request.json                         # full {"state","questions"} for a batch
```

`--state` takes a literal string; omit both flags and state is read from stdin.
Add `--id meaningful_name` so the answer key reads well.

## Rules

- **One judgment per question.** "Is it spam and urgent?" is two questions.
- **Batch shared state.** Many questions, one `jev ask` call; they run in parallel
  and the state is paid once. Questions cannot see each other.
- **Every field must earn its place.** Irrelevant context lowers accuracy.
- **Name the discriminating case in the criteria** when two options are confused.
- **Answer in code.** Top option is the default; for a Noul, 0.7 / 0.3 are starting
  thresholds and the band between means "not settled". Do not gate on `confidence`.
- **Never invent options at call time**; keep question wording in one file in the
  project so it can be reviewed.

## Cost

Pennies per call. Probe representative, hard, and negative cases before wiring a
threshold, and keep the payloads so a result can be rerun.
