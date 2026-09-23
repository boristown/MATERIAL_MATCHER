# Issue #162 performance report

## Goal and acceptance boundary

Issue #162 targets one 40,000 SAP × 1,000,000 group-code task completing end to end within 60 minutes without changing thresholds, disabling semantic matching, reducing configured TopK, dropping Top1/Top5 data, or removing traceability.

Synthetic benchmarks below validate engineering scale only. They do not replace the required production-model, business-gold, customer-class-hardware acceptance run, so Issue #162 remains open until that formal gate is passed.

## Audit and implementation

Before this change the target embedding/index cache was reusable, but GLOBAL vector retrieval still scanned all target vector blocks for each source query. Indexed task results were retained in Python, match rows/candidates were issued as individual SQL statements, and task progress wrote SQLite state on every source row.

The optimized GLOBAL path now uses a persisted multi-table sign-LSH recall layer over the existing mmap BBQ/int8 index. Source query batches use a configurable bounded worker pool and share the same mmap index. Recalled candidates remain bounded, then the existing vector rerank, field scoring, decision, Top1/Top5 and persistence logic runs unchanged. Pathological low-entropy buckets fall back to the existing blockwise exact scan before an oversized candidate union is materialized, preserving recall rather than silently dropping candidates.

Indexed results can stream directly to bounded persistence batches. match_items and match_candidates use executemany. Progress writes are heartbeat-throttled.

## Configuration

- MATERIAL_MATCHER_MATCH_WORKERS, default 4
- MATERIAL_MATCHER_MATCH_BATCH_ROWS, default 256
- MATERIAL_MATCHER_QUERY_BATCH_SIZE, default 64
- MATERIAL_MATCHER_PROGRESS_UPDATE_SECONDS, default 1.0
- MATERIAL_MATCHER_ANN_MIN_ROWS, default 100000
- MATERIAL_MATCHER_ANN_LSH_TABLES, default 48
- MATERIAL_MATCHER_ANN_LSH_BITS, default 16
- MATERIAL_MATCHER_ANN_PROBE_RADIUS, default 1
- MATERIAL_MATCHER_ANN_CANDIDATE_LIMIT, default 12000

## Observability

The task records parsing, normalization, target index build/load, source preprocessing, retrieval, rerank/scoring, decision, DB persistence and finalize timing; wall time; rows/s; worker and batch settings; index reuse; peak RSS; CPU time; returned TopK counts; ANN recall-pool counts; vector-rerank counts; and ANN exact-fallback query count.

STEP2 keeps phase, processed/total rows, throughput/ETA and live status counts, and adds worker/batch settings plus the latest heartbeat.

## Reproducible benchmark

scripts/benchmark_issue_162.py supports:

| preset | source | target |
|---|---:|---:|
| quick | 1,000 | 100,000 |
| stress | 10,000 | 1,000,000 |
| formal | 40,000 | 1,000,000 |

It generates deterministic CSV fixtures, supports cold/warm runs, and has --disable-ann to force the legacy flat retrieval path for same-build before/after comparison. The same tool can also exercise the installed production ONNX provider on the generated scale fixture:

```bash
python scripts/benchmark_issue_162.py \
  --preset formal \
  --provider onnx_local \
  --model-id BAAI/bge-base-zh-v1.5 \
  --dimensions 768 \
  --precision int8 \
  --warm-runs 2 \
  --output issue-162-formal-production-model.json
```

The production-model mode requires the offline ONNX/tokenizer bundle already installed under MATERIAL_MATCHER's model root. Generated data validates scale and throughput only; business accuracy must still be checked with the existing gold-set evaluation flow.

## Measured GitHub Actions results

Reference runner: AMD EPYC 7763, 4 logical CPUs available, 15,989.7 MB RAM, no GPU, Linux Azure, Python 3.11.16. Benchmark parameters: 4 workers, query batch 64, persist batch 256, TopK 50, TopN 5, deterministic 32-dimensional synthetic embeddings. These numbers are not production BGE performance.

### 1,000 × 100,000 — CI run #502

| run | index | wall | rows/s | peak RSS |
|---|---|---:|---:|---:|
| cold | build | 52.678 s | 18.983 | 151.066 MB |
| warm-1 | reused | 44.974 s | 22.235 | 158.129 MB |

Cold stages: index 7.445 s, retrieval 40.965 s, rerank/field scoring 4.017 s, DB persistence 0.143 s. Warm index load was 0.0017 s. Synthetic exact-fixture Top1 accuracy was 1.0.

### 10,000 × 1,000,000 — CI run #506

Cold wall time was 293.785 s at 34.039 rows/s with peak RSS 590.652 MB. Stages: index 105.710 s, retrieval 145.496 s, rerank/field scoring 40.130 s, DB persistence 1.427 s. Synthetic exact-fixture Top1 accuracy was 1.0.

### 40,000 × 1,000,000 — CI run #507

GitHub Actions completed the full synthetic engineering-scale run successfully on the same 4-vCPU / ~16-GB runner:

| run | index | wall | rows/s | peak RSS |
|---|---|---:|---:|---:|
| cold | build | **861.788 s (14.36 min)** | **46.415** | **599.246 MB** |

Cold stages: target index build/load 112.534 s, source preprocessing 1.406 s, retrieval 578.284 s, rerank/field scoring 160.367 s, DB persistence 6.188 s, finalize 0.105 s. The ANN recall pool averaged 9,193.499 rows/query (P95 9,353; max 9,595) instead of scanning 1,000,000 rows/query. Vector rerank stayed at exactly 200 candidates/query, returned TopK stayed at 50, no ANN fallback occurred, and all 40,000 rows were persisted. Synthetic exact-fixture Top1 accuracy was 1.0.

This is strong evidence that the implementation no longer has the original 40-billion-pair scaling shape and that the engineering path has substantial headroom against the 60-minute target on this runner. It is still **not** the Issue #162 formal production acceptance result because the run used deterministic 32-dimensional test embeddings rather than the production BAAI/bge-base-zh-v1.5 ONNX model and customer gold data.

## Correctness status

The existing suite passed before the formal-scale run: 289 tests with one unrelated Starlette deprecation warning. Existing real-world scan quality evaluation passed. CI explicitly reports that the production BGE vector path is not formally quality-evaluated because the real model is not loaded. The performance change does not alter thresholds, value_mapping, critical-conflict rules, score formulas, Top1/Top5 semantics, or traceability fields.

## Remaining formal closure gates

Issue #162 remains open until production-model/business-gold validation on customer-class-or-lower hardware completes one cold and two warm 40k×1M runs, each required quality comparison is recorded, end-to-end time is within 60 minutes, API/health responsiveness is observed during the long task, and final hardware/deployment/storage details (plus GPU utilization/peak VRAM if GPU is used) are documented.
