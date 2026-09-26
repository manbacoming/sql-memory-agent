# Open Decisions

This document lists decisions that must be resolved with real data or small controlled checks. None of these items should be presented as solved yet.

## 1. Whether BIRD Fits the 50 GB Data Disk

Current server storage:

- system disk: about 30 GB, too small for large project artifacts;
- data disk: `/root/autodl-tmp`, about 50 GB.

Open question:

- Do the required BIRD train/dev files, SQLite databases, derived task streams, logs, and intermediate outputs fit comfortably inside 50 GB together with model files?

Recommendation:

- Before downloading anything large, check official dataset sizes and expected decompressed database size.
- Keep raw data under `/root/autodl-tmp/sql-memory-agent-data`.
- Keep models under `/root/autodl-tmp/sql-memory-agent-models`.
- Keep outputs/checkpoints under `/root/autodl-tmp/sql-memory-agent-outputs` and `/root/autodl-tmp/sql-memory-agent-checkpoints`.
- If BIRD plus models cannot fit, use a smaller fixed agent, remote-mounted model cache, or a reduced pilot dataset.

Rationale:

- The system disk is only about 30 GB and should not hold datasets, checkpoints, model weights, or large logs.

## 2. How to Construct Same-Database Task Streams

Open question:

- How should tasks be ordered so that previous memory can plausibly help later tasks from the same or related database without leaking future answers?

Candidate approaches:

1. Group tasks by `db_id`, then create chronological streams within each database.
2. Use schema elements or query templates to cluster related tasks.
3. Create database-update scenarios where a schema/value change occurs between task segments.
4. Reserve some databases exclusively for test streams to avoid cross-split leakage.

Recommendation:

- Start with grouped-by-database streams because they are simple and auditable.
- Then add controlled update events only after the baseline memory/no-memory comparison is stable.

Rationale:

- Cross-task memory is most interpretable when tasks share database semantics. However, grouping must not reveal test answers or future labels.

## 3. How to Verify Semantic Branches

Open question:

- What verifier is reliable enough to decide whether a memory branch, SQL rewrite, or semantic statement should be used as a positive training signal?

Candidate verification methods:

- exact SQL execution match against gold result;
- result-set equivalence under deterministic database snapshots;
- static SQL checks for schema validity;
- human-reviewed semantic labels for a small validation subset;
- conservative verifier that outputs `unknown` when evidence is insufficient.

Recommendation:

- Use SQL execution equivalence as the first verifier where possible.
- Treat unverifiable branches as `unknown`, not positive.
- Log the reason for every `unknown` branch.

Rationale:

- The protocol requires that only reliably checked branches enter training as passed examples.

## 4. Which Fixed SQL Agent to Use

Open question:

- Which SQL Agent can run on one RTX 4080 SUPER with available memory while staying fixed across experiments?

Observed hardware at initialization:

- GPU: NVIDIA GeForce RTX 4080 SUPER, about 32 GB VRAM.
- Existing Python environment: `/root/miniconda3/bin/python`, Python 3.12.3.
- Existing PyTorch package: torch 2.8.0+cu128.

Candidate directions:

1. Use a small local open-weight model that fits comfortably on 32 GB VRAM.
2. Use an API-backed model if allowed by budget and reproducibility constraints.
3. Use a retrieval/tool wrapper around a fixed Text-to-SQL model for early pilots.

Recommendation:

- Choose the smallest fixed agent that can solve pilot SQL tasks reliably enough to expose memory effects.
- Freeze all model/tool/decoding settings before comparing memory policies.
- Do not make model upgrades part of the memory-policy comparison.

Rationale:

- The experiment should measure memory management, not changing model capability.

## 5. Memory Schema and Actions

Open question:

- What exactly is stored in long-term memory?

Candidate memory fields:

- natural-language observation;
- related `db_id` and schema elements;
- SQL pattern or reusable clause;
- verified status;
- database snapshot ID;
- creation task ID;
- last verified task ID;
- staleness marker;
- confidence or verifier reason.

Candidate actions:

- write,
- update,
- delete,
- mark stale,
- retrieve,
- withhold.

Recommendation:

- Start with a compact JSONL memory schema and append-only audit log.
- Keep mutable memory state derivable from the audit log.

Rationale:

- RL over memory actions needs clear, auditable state transitions.

## 6. Reward Design

Open question:

- How should reward balance final correctness, memory usefulness, memory cost, and stale-memory risk?

Recommendation:

- Primary reward should be final correctness.
- Secondary penalties can include unnecessary memory count, extra turns, and verified stale-memory use.
- Do not reward unverified branches as correct.

Rationale:

- The protocol prioritizes final correctness before efficiency.

## 7. Pilot Before Full Training

Open question:

- What is the smallest pilot that validates the full pipeline without consuming too much disk or GPU time?

Recommendation:

- Use a small fixed subset with a few databases, explicit task ordering, and hand-inspected memory logs.
- Only after the pilot validates data flow, verifier behavior, and split isolation should full RL training be attempted.

Rationale:

- The project is new; the main risk is invalid experimental design, not lack of training time.
﻿
## 8. Data Size Feasibility Update

Status on 2026-09-26: partially investigated; not fully solved because no full archive was downloaded or extracted.

Known facts:

- Official BIRD `train.zip` was checked with HTTP HEAD only: 8,919,543,554 bytes.
- Official BIRD `dev.zip` was checked with HTTP HEAD only: 346,207,293 bytes.
- The official BIRD site reports 33.4 GB total database size across 95 databases.
- `bird23-train-filtered` provides a 6,601-example filtered train metadata split, but it does not remove the need for train SQLite databases.

Decision for now:

- The first real-data step should use official `dev.zip` for loader/evaluator validation.
- Full train should wait until a fresh disk check and explicit approval, because compressed plus extracted data may fit in 50 GB but leaves little margin for models or generated outputs.

See `docs/DATA_FEASIBILITY.md` for detailed sources, byte counts, and proposed download sequence.
