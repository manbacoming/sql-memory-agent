# Next Steps

This handoff records the current checkpoint for the independent `sql-memory-agent` project.

## 1. Core Research Questions

The project studies SQL Agents with cross-task long-term memory. Two questions define the main line of work:

1. Does saved memory from earlier tasks help solve later new SQL tasks?
2. When a database changes, when should old memory be kept, updated, quarantined, or deleted?

The second question is central. Memory can become stale because a schema, table, column, value distribution, or business rule changes. The project should measure both immediate correctness and the future utility or harm of memory lifecycle decisions.

## 2. Paper Positioning

Prior work already studies retrieval, memory, demonstration selection, and experience reuse for future tasks. We should not claim that the general idea of memory helping later questions is unstudied.

The intended contribution is narrower and more specific:

- database-conditioned long-term memory for Text-to-SQL task streams;
- memory validity under database/schema/content changes;
- lifecycle decisions such as `KEEP`, `UPDATE`, `QUARANTINE`, and `DELETE`;
- measuring whether memory that was once useful remains useful, becomes harmful, or should be withheld;
- training or learning a policy for memory selection and management based on verified outcomes.

The toy experiment in this repository is not evidence for a paper claim. It is only a protocol and engineering check.

## 3. What Was Completed Today

Project structure was created under:

```text
/root/autodl-tmp/sql-memory-agent
```

External artifact directories were created outside Git:

```text
/root/autodl-tmp/sql-memory-agent-data
/root/autodl-tmp/sql-memory-agent-models
/root/autodl-tmp/sql-memory-agent-outputs
/root/autodl-tmp/sql-memory-agent-checkpoints
```

Implemented source files:

```text
src/sql_memory_agent/models.py
src/sql_memory_agent/example_data.py
src/sql_memory_agent/sqlite_eval.py
src/sql_memory_agent/memory.py
src/sql_memory_agent/solver_stub.py
src/sql_memory_agent/paired_eval.py
src/sql_memory_agent/driver.py
scripts/run_toy_experiment.py
tests/test_toy_protocol.py
```

Documentation files:

```text
README.md
docs/experiment_protocol.md
docs/open_decisions.md
docs/NEXT_STEPS.md
```

## 4. Current Toy Experiment

The current toy experiment requires no BIRD download, no model download, no external Python dependency, and no GPU.

It generates two tiny SQLite databases outside the Git repo:

```text
/root/autodl-tmp/sql-memory-agent-data/toy/retail_v1.sqlite
/root/autodl-tmp/sql-memory-agent-data/toy/retail_v2.sqlite
```

The v1 database contains:

- `cities`
- `stores`
- `orders`
- `refunds(refund_amount)`

The v2 database changes the refund schema to:

- `refund_events(returned_amount, approved)`

The data is intentionally small but diagnostic:

- gross sales rank `Metropolis` first;
- net sales after refunds rank `Gotham` first;
- therefore failing to deduct refunds produces a distinguishable wrong answer.

The sequence starts from an empty memory store. A v1 task creates a refund-rule memory. A later v1 task can retrieve it. When the stream switches to v2, memories depending on `refunds.refund_amount` are quarantined before retrieval, so stale v1 memory cannot be used on v2.

## 5. Deterministic Stub Boundary

The current solver is explicitly a testing stub:

```text
src/sql_memory_agent/solver_stub.py
```

It is not a real SQL Agent and not a model. It deterministically chooses one of a few SQL templates based on the database version and retrieved memories. Its purpose is to make the protocol testable today:

- retrieval happens once per question;
- current-task writes are unavailable until later tasks;
- quarantined/deleted memory is not retrieved;
- empty-memory and selected-memory settings are paired on the same database snapshot;
- correctness dominates turn count in scoring.

Do not report toy stub correctness as model performance.

## 6. Test Command and Current Result

Automatic protocol checks:

```bash
cd /root/autodl-tmp/sql-memory-agent
PYTHONPATH=src /root/miniconda3/bin/python -m unittest discover -s tests -v
```

Current result:

```text
Ran 4 tests in about 0.08 seconds
OK
```

The tests cover:

- current task cannot retrieve memory it just wrote;
- v1 memory is not retrievable after the v2 schema change;
- paired empty-memory and selected-memory evaluations use the same database version;
- a wrong answer with fewer turns scores below a correct answer with more turns.

Toy demo command:

```bash
cd /root/autodl-tmp/sql-memory-agent
/root/miniconda3/bin/python scripts/run_toy_experiment.py
```

Observed demo summary:

```text
events: 16
memories:
  mem_v1_refund_rule: QUARANTINED, retail_v1
  mem_v2_refund_rule: ACTIVE, retail_v2
operations:
  ADD, KEEP, QUARANTINE, ADD
```

## 7. Next Work Order

Recommended next sequence:

1. Verify real data size and legal/download method.
   - Check BIRD train/dev archive sizes and decompressed SQLite sizes before downloading.
   - Confirm everything fits within `/root/autodl-tmp`, not the 30 GB system disk.

2. Connect real tasks without leaking gold information.
   - Build task records from real question/database metadata.
   - Ensure test gold SQL, final answers, and future task information never enter agent input or memory.

3. Choose and freeze a fixed SQL Agent.
   - Pick a model/tool setup that can run on the RTX 4080 SUPER budget.
   - Freeze prompts, decoding, tool budget, and random seeds before comparing memory strategies.

4. Measure memory utility on future tasks.
   - Start with empty memory.
   - Use grouped-by-database task streams.
   - Compare no-memory versus retrieved-memory conditions with paired seeds and same database snapshots.

5. Construct database-change task streams.
   - Introduce schema/content changes with explicit database version IDs.
   - Track which memories depend on changed tables/columns/values.
   - Test `KEEP`, `UPDATE`, `QUARANTINE`, and `DELETE` policies.

6. Train memory selection and management.
   - Only after verifier and stream construction are stable.
   - Do not train on unverifiable positive labels.
   - Treat unknown branch outcomes as unknown, not successful.

## 8. Unresolved Items

Still unresolved:

- BIRD size versus 50 GB data disk budget.
- Exact BIRD download/staging method.
- How to construct same-database streams without train/test leakage.
- How to represent database updates for realistic Text-to-SQL tasks.
- Which fixed SQL Agent to use.
- How to verify semantic memory branches beyond exact SQL execution.
- Persistent memory storage format for real runs.
- RL state/action/reward design.
- Validation/test isolation protocol on real data.

## 9. First Commands Next Time

Start with these read-only checks:

```bash
cd /root/autodl-tmp/sql-memory-agent
git status --short
git log --oneline -n 5
find . -maxdepth 3 -type f | sort
PYTHONPATH=src /root/miniconda3/bin/python -m unittest discover -s tests -v
/root/miniconda3/bin/python scripts/run_toy_experiment.py >/tmp/sql_memory_agent_toy_check.json
/root/miniconda3/bin/python - <<'PY'
import json
p = '/tmp/sql_memory_agent_toy_check.json'
data = json.load(open(p))
print('events', len(data['events']))
print('memories', [(m['memory_id'], m['status'], m['applies_to_db_version']) for m in data['memories']])
print('operations', [o['op_type'] for o in data['operations']])
PY
rm -f /tmp/sql_memory_agent_toy_check.json
```

Before any large operation, check disk:

```bash
df -h / /root/autodl-tmp
```

Do not put datasets, models, outputs, or checkpoints on the system disk.
