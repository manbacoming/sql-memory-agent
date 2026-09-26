# Data Feasibility Notes

Date: 2026-09-26

This note records a no-download feasibility check for using real Text-to-SQL data in the SQL Memory Agent project. It is not an experiment result.

## Sources Checked

1. BIRD official site: https://bird-bench.github.io/
   - The site describes BIRD-SQL as a large-scale database-grounded Text-to-SQL benchmark.
   - It reports over 12,751 question-SQL pairs, 95 databases, and total database size of 33.4 GB.
   - It provides official `Train Set` and `Dev Set` download links.

2. Official BIRD download URLs checked with HTTP HEAD only, no dataset body downloaded:
   - `https://bird-bench.oss-cn-beijing.aliyuncs.com/train.zip`
   - `https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip`

3. BIRD Team Hugging Face filtered train dataset:
   - https://huggingface.co/datasets/birdsql/bird23-train-filtered
   - The dataset card says it keeps 6,601 instances out of the original 9,428 train examples, about 70%.
   - The repository tree reports about 3.45 MB for the filtered metadata repository and about 786 kB for `train_column_meaning.json`.
   - It still requires the BIRD train databases under `train_databases/` for SQL execution.

## Header Results From This Server

Commands used:

```bash
curl -L -I --max-time 30 https://bird-bench.oss-cn-beijing.aliyuncs.com/train.zip
curl -L -I --max-time 30 https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip
```

Observed headers:

| File | Content-Length bytes | Approx decimal GB | Approx GiB | Last-Modified |
|---|---:|---:|---:|---|
| `train.zip` | 8,919,543,554 | 8.92 GB | 8.31 GiB | 2023-07-11 |
| `dev.zip` | 346,207,293 | 0.35 GB | 0.32 GiB | 2024-06-29 |

Both URLs returned `HTTP/1.1 200 OK`, `Content-Type: application/zip`, and `Accept-Ranges: bytes`.

## Disk Feasibility On Current AutoDL Data Disk

Current data disk target:

```text
/root/autodl-tmp
```

Previously observed capacity:

```text
/root/autodl-tmp: about 50 GB total
```

Important space implications:

- BIRD official site reports 33.4 GB total database size across 95 databases.
- If the full dataset archive and extracted data coexist, space may be tight but likely possible for data only: roughly 33.4 GB extracted + 8.92 GB train archive + 0.35 GB dev archive = about 42.7 GB before logs and temporary files.
- This leaves too little margin for model weights, checkpoints, or large generated outputs on the same 50 GB disk.
- Therefore do not download model weights together with full BIRD until disk layout is decided.
- If full train is downloaded, plan to remove the zip after verifying extraction and checksums, or use a larger data disk.

## Recommended First Data Scope

Recommended first phase: metadata and dev-first, then train databases only after a disk checkpoint.

1. Start with official BIRD `dev.zip`.
   - Small compressed size: about 346 MB.
   - Useful for validating loaders, schemas, SQLite execution, and gold-leakage boundaries.
   - It is not training data, so use it only for pipeline development or evaluation-style checks, not for claiming training results.

2. Add `birdsql/bird23-train-filtered` metadata.
   - Small metadata repository, about 3.45 MB according to the Hugging Face tree.
   - Gives a 6,601-example filtered train split.
   - Does not replace the train SQLite databases.

3. Before downloading full `train.zip`, run a disk check and choose one of these plans:
   - Plan A: download `train.zip`, extract under `/root/autodl-tmp/sql-memory-agent-data/bird/train`, verify layout, then delete the zip to recover about 8.31 GiB.
   - Plan B: attach or switch to a larger data disk before full train extraction.
   - Plan C: if only agent protocol work is needed, use dev or a small manually staged subset until full train storage is available.

## Recommended Directory Layout

Use only the data disk:

```text
/root/autodl-tmp/sql-memory-agent-data/bird/raw
/root/autodl-tmp/sql-memory-agent-data/bird/extracted
/root/autodl-tmp/sql-memory-agent-data/bird/dev
/root/autodl-tmp/sql-memory-agent-data/bird/train
/root/autodl-tmp/sql-memory-agent-data/bird/filtered_train
```

Do not put BIRD data under `/root` or inside the Git repo.

## Gold-Leakage Boundary For Next Implementation

The next real-data loader must keep these fields separate:

- Agent input may include question, schema, allowed database snapshot, and optionally evidence if the experiment explicitly allows it.
- Gold SQL and final answer/results are evaluator-only.
- Future task records must not enter current memory.
- Memory starts empty for each stream.
- Current task memory writes become available only for later tasks.
- Each task retrieves memory once.

## Next Concrete Download Plan

No download was performed in this check. A safe next command sequence, after explicit approval, would be:

```bash
cd /root/autodl-tmp/sql-memory-agent
df -h / /root/autodl-tmp
mkdir -p /root/autodl-tmp/sql-memory-agent-data/bird/raw
cd /root/autodl-tmp/sql-memory-agent-data/bird/raw
curl -L -C - -o dev.zip https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip
unzip -l dev.zip | sed -n '1,80p'
```

Only after inspecting the dev layout should extraction proceed.

For full train, require a second approval and a fresh disk check:

```bash
df -h /root/autodl-tmp
curl -L -C - -o train.zip https://bird-bench.oss-cn-beijing.aliyuncs.com/train.zip
unzip -l train.zip | sed -n '1,80p'
```

Do not download models in the same step.

## Current Recommendation

For the next coding step, implement a BIRD dev/filtered-train metadata loader interface first, without downloading full train. The first real data run should use official `dev.zip` to validate SQLite execution and anti-leakage boundaries. The first training-oriented stream should use `bird23-train-filtered` metadata plus train databases only after confirming extraction fits and the zip can be removed.
