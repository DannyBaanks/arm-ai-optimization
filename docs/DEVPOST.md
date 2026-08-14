# Devpost submission — Arm AI Optimization Harness

Copy-paste source for the submission form. Every number here is committed in
the repo under `evidence/arm64_ci/` and rendered in `results/arm64/`.

---

## Elevator pitch (200 char limit)

A deterministic test harness that measures whether your inference execution
strategy actually helps on Arm64 — and proves it with signed, reproducible
evidence.

---

## What we measured (lead with this)

Real Arm64 hardware: GitHub-hosted `ubuntu-24.04-arm` runner, Azure Cobalt
silicon. Model `qwen2.5-0.5b-instruct`. 8 requests × 3 repeats, 4 workers.

| Runtime configuration | Sequential | Dataflow | Wall-time | tokens/s |
|---|---|---|---|---|
| Ollama, `OLLAMA_NUM_PARALLEL=4` | 9.68s | 10.13s | **0.955×** | 52.9 → 50.5 |
| Ollama, `num_thread=1` | 21.99s | 20.50s | **1.072×** | 22.1 → 25.0 |
| **llama-server `--parallel 4 -t 1`** | 23.26s | 16.88s | **1.378×** | 22.0 → **30.3** |

The workflow asserts `uname -m == aarch64` and fails the job otherwise. This
evidence cannot be produced on an x86 machine.

---

## Inspiration

Platform engineers deploying small models on Arm64 clusters face a question
with no good answer: does parallelizing inference actually help on this
hardware, or does it just burn cycles?

The available answers are vendor benchmarks measured on someone else's
hardware, or blog posts that assume x86 or GPU. Neither survives contact with
a specific Neoverse box running a specific model under a specific runtime.

We wanted an instrument, not an opinion.

## What it does

Runs an identical workload two ways — sequential (fresh context per request)
versus dataflow (pooled workers) — through the same runtime adapter, so the
metrics are actually comparable. It emits SHA256-signed evidence for every
run, verifies those signatures, and feeds a scheduler that picks a deployment
target from measured numbers rather than hand-tuned weights.

The runtime is a plugin, not a dependency: Ollama, llama-server, or anything
that speaks JSONL over stdio.

## How we built it

Three components with hard boundaries:

1. **Harness** (`armopt.runner`) — same workload, two execution strategies,
   one output contract.
2. **Signed evidence** (`armopt.evidence`) — one canonical hashing rule, used
   by every producer. `verify_evidence()` recomputes and rejects any file
   edited after signing.
3. **Scheduler** (`armopt.scheduler`) — min-max normalized scoring over
   latency, cost and throughput from the evidence files.

Arm64 measurement runs in GitHub Actions on `ubuntu-24.04-arm`, which is free
for public repos — no cloud account, no SSH, no credit card. The job installs
Ollama, compiles llama.cpp from source, benchmarks three configurations under
identical conditions, and commits the resulting evidence back into the repo so
it does not depend on artifacts that expire.

## Challenges we ran into

**The obvious optimization made things slower.** Our first Arm64 run came back
at 0.955× — parallelizing was a regression. Ollama's CPU build does not
overlap requests on this hardware. We had to rule that out across three
configurations before finding that llama.cpp's `--parallel` slots do give real
concurrency, at 1.378×.

**We caught ourselves shipping mislabeled evidence.** Our results generator
wrote to `results/arm64/` while running the in-memory demo adapter on a
Windows x86 laptop — producing files named `arm64_*` whose contents read
`"architecture": "AMD64"`. Nobody faked anything; a path was wrong. But it was
indistinguishable from fabrication to anyone auditing it.

The fix became a feature: `build_arm64_results.py` re-verifies every signature
and **aborts** if a platform string is not `aarch64`, so Arm64 results can only
be derived from Arm64 evidence. CI re-runs it on every push and fails if the
committed results drift from the evidence they claim to summarize.

## Accomplishments we're proud of

**The scheduler disagreed with the headline number, and it was right.**

| | mean latency | tokens/s | wall-time speedup |
|---|---|---|---|
| Ollama | **4,415 ms** | **50.5** | 0.955× |
| llama-server | 8,441 ms | 30.3 | **1.378×** |

llama-server wins wall-clock throughput on a batch and loses everything a
serving tier is judged on — nearly double the per-request latency, 40% less
token throughput. The scheduler deployed Ollama. Nobody programmed that
preference; it fell out of normalized scoring over measured evidence.

Shipping the 1.378× number alone would have been a defensible-looking mistake.
The harness caught it.

## What we learned

Wall-time speedup is a batch metric. Latency is a user metric. On constrained
Arm64 cores they routinely disagree, and which one you optimize is a product
decision that benchmarks alone cannot make for you — but they can make the
tradeoff visible instead of invisible.

We also learned that runtime choice dominated configuration tuning. Every
knob we turned on Ollama moved the number by single-digit percent; switching
to llama-server moved it by 40%.

## Built with

Python 3.12 · Rust · GitHub Actions (`ubuntu-24.04-arm`) · llama.cpp ·
Ollama · Qwen2.5-0.5B-Instruct (GGUF q4_k_m) · WASM (`wasm32-wasip1`) ·
GnuCOBOL

## What's next

- Sustained load rather than 8-request batches
- Larger models, where the parallelism story likely changes once weights stop
  fitting in cache
- A real cost dimension — every runtime we measured is local and free, so
  `cost_per_1k_tokens` is currently 0.0 throughout
- GPU/NPU delegates

---

## If asked: why the esoteric languages?

Robustness of an evaluation harness is a measurable property, not a claim. A
harness that runs other people's runtimes has to survive input designed to
break it, so we test it against **Malbolge** — a language engineered to be
maximally hostile: self-modifying code, ternary arithmetic, memory that
re-encrypts itself after every instruction, and no termination guarantee.

4/4 survival. Non-termination and illegal instructions come back as contract
outcomes, never as a crashed measurement run.

The same contract discipline lets four unrelated engines (Python, Rust, COBOL,
WASM) report into one comparison — and makes the harness **refuse** to compare
Python against COBOL, because they declare different contract types. Declining
an invalid comparison is a feature, not a gap.

---

## Verification for judges

```bash
# Check any evidence signature
python -c "from pathlib import Path; from armopt.evidence import verify_evidence; \
print(verify_evidence(Path('evidence/arm64_ci/arm64_llama_server.json')))"

# Rebuild results/arm64/ from signed evidence (aborts if not aarch64)
python scripts/build_arm64_results.py

python -m pytest tests/ -q          # 27 tests
python scripts/malbolge_stress.py   # 4/4 harness survival
```

**Honest limitations** are listed in the repo README and not hidden: small
workload (8 requests), small model (0.5B), CPU only, inert cost dimension,
and cross-engine conformance numbers measured on x86 — those validate contract
compatibility, not Arm64 performance.
