# Arm AI Optimization Harness

[![Tests](https://github.com/DannyBaanks/arm-ai-optimization/actions/workflows/ci.yml/badge.svg)](https://github.com/DannyBaanks/arm-ai-optimization/actions/workflows/ci.yml)
[![Arm64 benchmark](https://github.com/DannyBaanks/arm-ai-optimization/actions/workflows/arm64-benchmark.yml/badge.svg)](https://github.com/DannyBaanks/arm-ai-optimization/actions/workflows/arm64-benchmark.yml)

A deterministic test harness for platform engineers deploying small models on
Arm64. It answers one question with evidence instead of intuition: **does your
execution strategy actually help on this hardware, or are you paying for idle
cycles?**

**Evidence before narrative.** Every number below is recomputable from signed
JSON committed in this repo. Nothing here was measured on a developer laptop
and relabelled.

---

## What we measured on real Arm64

<!-- ARM64_HOST:START -->
GitHub-hosted `ubuntu-24.04-arm` runner: **Neoverse-N2**, 4 cores, `Linux-6.17.0-1022-azure-aarch64-with-glibc2.39`. Recorded by the runner itself in [`evidence/arm64_ci/host.json`](evidence/arm64_ci/host.json).
<!-- ARM64_HOST:END -->

Model: `qwen2.5-0.5b-instruct`. 8 requests, 3 repeats, 4 workers in dataflow
mode. The workflow asserts `uname -m == aarch64` and **fails the job** if it is
not, so this evidence cannot be produced off-target.

<!-- ARM64_TABLE:START -->
| Runtime configuration | Sequential | Dataflow | Wall-time | tokens/s |
|---|---|---|---|---|
| Ollama, default per-request threading (OLLAMA_NUM_PARALLEL=4) | 10.01s | 9.84s | **1.018x** | 51.1 -> 52.0 |
| Ollama, capped per-request threading (num_thread=1) | 22.05s | 20.20s | **1.091x** | 23.2 -> 25.3 |
| **llama-server, --parallel 4 -t 1** | 22.86s | 16.94s | **1.35x** | 22.4 -> 30.2 |
<!-- ARM64_TABLE:END -->

Evidence: [`evidence/arm64_ci/`](evidence/arm64_ci/) · Rendered:
[`results/arm64/`](results/arm64/)

Every measured number in this README is generated from that evidence by
`scripts/build_arm64_results.py`, and CI fails if the two disagree. Nobody
types a benchmark result into this file by hand -- that is how a repo ends up
quoting four contradictory speedups.

**The obvious configuration buys nothing.** Across repeated CI runs, Ollama
with `OLLAMA_NUM_PARALLEL=4` lands on either side of 1.0x -- 0.955x, 0.975x,
1.018x -- which is the signature of no real concurrency, not of a small win.
Its CPU build does not overlap requests on this hardware; llama.cpp's
`--parallel` slots do, consistently. We did not know that going in. The harness
is what told us, and a harness that only ever confirms the hypothesis is not an
instrument.

---

## The finding worth your attention

Given that evidence, the scheduler deployed **Ollama** — *not* the configuration
with the best speedup.

<!-- SCHEDULER_TABLE:START -->
| | mean latency | tokens/s | wall-time speedup |
|---|---|---|---|
| **Ollama** (deployed) | **4,318 ms** | **52.0** | 1.018x |
| llama-server | 8,468 ms | 30.2 | 1.35x |
<!-- SCHEDULER_TABLE:END -->

llama-server wins wall-clock throughput on a batch of 8 and loses everything a
serving tier is judged on: it nearly doubles per-request latency and gives up
roughly 40% of token throughput. Wall-time speedup is a batch metric. Latency
is a user metric. **They disagree here, and the disagreement is the product.**

Nobody hand-tuned that decision. `armopt.scheduler` scores min-max normalized
latency, cost and throughput from the measured evidence files — see
[`evidence/arm64_ci/selection.json`](evidence/arm64_ci/selection.json).

This is why the harness exists. Shipping the best speedup number alone would
have been a defensible-looking mistake.

---

## How it works

```text
workload → runtime adapter → { sequential | dataflow } → metrics
                                                            ↓
                                          signed evidence (SHA256)
                                                            ↓
                                              verify → scheduler → decision
```

Three components, no fakes:

1. **Harness** (`armopt.runner`) — identical workload run two ways: sequential
   (fresh context per request) vs dataflow (pooled workers). Same adapter, same
   output contract, therefore comparable metrics.
2. **Signed evidence** (`armopt.evidence`) — inputs, outputs, platform string
   and a content hash per run. `verify_evidence()` recomputes it and fails on
   any post-hoc edit. One canonical hashing rule, because a signing scheme with
   three copies is three schemes.
3. **Scheduler** (`armopt.scheduler`) — min-max normalized scoring over measured
   evidence, not hand-tuned weights.

**Runtime is a plugin, not a dependency.** `HttpAdapter` covers Ollama and
llama-server; `JsonlAdapter` covers anything that speaks JSONL over stdio.

---

## Quick start

```powershell
python -m venv .venv
python -m pip install -e .
python -m armopt
```

```
[1] Run benchmark          [5] Show latest decision
[2] Compare providers      [6] Run full pipeline
[3] Run scheduler          [7] View system status
[4] Verify evidence        [0] Exit
```

Scriptable, which is what CI uses:

```bash
# Smoke test, no AI runtime required
python -m armopt.cli --demo --requests 32 --workers 4 --mode both

# Against a real runtime
python -m armopt.cli --adapter http --http-url http://localhost:11434 \
  --http-model qwen2.5:0.5b --workload-file workloads/demo.json \
  --workers 4 --repeats 3 --mode both --evidence evidence/run.json

# Scheduler decision from evidence
python -m armopt.select --evidence evidence/a.json --evidence evidence/b.json
```

---

## Resilience: surviving pathological workloads

A harness for other people's runtimes has to survive input designed to break
it. Robustness here is measured, not asserted — we run **Malbolge**, a language
engineered to be maximally hostile: self-modifying code, ternary arithmetic,
memory that re-encrypts itself after every instruction, and no guarantee of
termination.

| Stress case | Outcome | Steps | Harness survived |
|---|---|---|---|
| `hello_world` | HALTED | 48 | ✓ |
| `infinite_loop_stress` | ILLEGAL:12 | 1 | ✓ |
| `self_modifying_stress` | HALTED | 48 | ✓ |
| `large_output` | ILLEGAL:69 | 2 | ✓ |

**4/4 survival.** Non-termination and illegal instructions are caught and
reported as contract outcomes — never as a crashed measurement run. Evidence:
[`evidence/stress_malbolge_stress.json`](evidence/stress_malbolge_stress.json).

The same contract discipline is what lets four unrelated engines report into
one comparison:

| Engine | Type | Target | Contract |
|---|---|---|---|
| Python | Inference | x86 / Arm64 | baseline + dataflow |
| Rust | Inference | Arm64 native | baseline + dataflow |
| COBOL | Batch | x86 (GnuCOBOL) | batch |
| WASM | Portable | `wasm32-wasip1` | baseline + dataflow |

`scripts/cross_engine_test.py` validates Python ↔ Rust field-for-field, and
**refuses** to compare either against COBOL: different contract types are
skipped, not forced into a shared ranking. Declining an invalid comparison is a
feature.

---

## Verify it yourself

```bash
# Check any evidence file's signature
python -c "from pathlib import Path; from armopt.evidence import verify_evidence; \
print(verify_evidence(Path('evidence/arm64_ci/arm64_llama_server.json')))"

# Rebuild results/arm64/ from the signed evidence
python scripts/build_arm64_results.py
```

`build_arm64_results.py` re-verifies every signature and **aborts** if a file's
platform string is not `aarch64`. That guard exists because this repo did once
ship `results/arm64/` files whose contents read `"architecture": "AMD64"` —
generated by the demo script writing into the wrong directory. The
demo generator now writes to [`results/demo/`](results/demo/), and Arm64
results can only come from Arm64 evidence.

Arm64 evidence is committed by the CI job itself, so it does not depend on
artifacts that expire.

---

## Status

| Capability | Status | Where |
|---|---|---|
| Arm64 benchmark CI | ✓ Measured on `ubuntu-24.04-arm` | `.github/workflows/arm64-benchmark.yml` |
| Signed evidence + verification | ✓ SHA256, one canonical rule | `src/armopt/evidence.py` |
| Scheduler from measured evidence | ✓ With regression test | `src/armopt/scheduler.py` |
| Deterministic tests | ✓ 27 passing | `python -m pytest tests/ -q` |
| Runtime adapters | ✓ Ollama, llama-server, JSONL | `src/armopt/*_adapter.py` |
| Rust native engine | ✓ Same contract, native Arm64 | `rust/armopt-native/` |
| COBOL batch engine | ✓ Contract compatibility | `rust/cobol-adapter/` |
| WASM target | ✓ `wasm32-wasip1` | `cargo build --target wasm32-wasip1` |
| Malbolge stress | ✓ 4/4 survival | `scripts/malbolge_stress.py` |

```bash
python -m pytest tests/ -q          # 27 tests
python scripts/cross_engine_test.py # cross-engine conformance
python scripts/malbolge_stress.py   # 4/4 harness survival
```

---

## Limitations

- **Small workload** — 8 requests × 3 repeats on Arm64 CI. Enough to rank
  configurations, not enough to characterize sustained production traffic.
- **Small model** — `qwen2.5-0.5b`. Larger models untested; the parallelism
  story likely changes when weights stop fitting in cache.
- **CPU only** — no GPU or NPU delegate measured.
- **Latency under dataflow rises** — concurrent requests share the same cores.
  This is reported in every result, not smoothed over.
- **Cost dimension is inert** — every runtime measured is local and free, so
  `cost_per_1k_tokens` is 0.0 throughout and exercised only by unit test.
- **Cross-engine numbers are x86** — the Python/Rust/COBOL conformance run in
  `scripts/cross_engine_test.py` validates *contract compatibility* on a
  developer machine. It is not an Arm64 performance claim.
- **WASM is single-threaded** — WASI threads are not stable, so its dataflow
  mode runs sequentially.
- **Malbolge is a stress fixture**, not a production runtime.

---

## License

MIT. See [`LICENSE`](LICENSE).
