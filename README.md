# Arm AI Optimization Harness

[![Arm64 benchmark evidence](https://github.com/DannyBaanks/arm-ai-optimization/actions/workflows/arm64-benchmark.yml/badge.svg)](https://github.com/DannyBaanks/arm-ai-optimization/actions/workflows/arm64-benchmark.yml)

A small, reproducible tool that measures whether a given execution
strategy actually speeds up AI inference on a given host -- runs the same
workload through real runtimes, writes signed evidence for every result,
verifies that evidence, and lets a scheduler pick a backend from the
*measured* numbers instead of a guess.

**Evidence before narrative.** Every claim in this README is backed by a
committed, hash-signed JSON file under `examples/evidence/`. Where
something hasn't been measured, it's listed under [Limitations](#limitations)
instead of implied.

```text
benchmark  →  evidence  →  verification  →  scheduler  →  decision
```

## Quick start

```powershell
python -m venv .venv
python -m pip install -e .
python -m armopt
```

`python -m armopt` opens an interactive menu -- a thin layer over the same
functions the plain CLIs call, nothing reimplemented underneath:

```text
Arm AI Optimization
--------------------
[1] Run benchmark
[2] Compare providers
[3] Run scheduler
[4] Verify evidence
[5] Show latest decision
[6] Run full pipeline
[7] View system status
[0] Exit
```

`[6] Run full pipeline` is the one-command version of the diagram above:
it detects which real runtimes are actually reachable right now, benchmarks
each of them, verifies the evidence it just wrote, asks the scheduler which
one it would deploy, and prints a plain-language summary -- hardware,
providers evaluated, what was measured, what was selected, why, and what
limits the decision. If no real runtime is reachable, it says so and stops;
it does not substitute a mock result to make the summary look complete.

The scriptable building blocks still work exactly as before and are what
CI actually uses:

```bash
python -m armopt.cli --demo --requests 32 --workers 4 --mode both   # harness smoke test, no AI
python -m armopt.cli --adapter http --http-url http://localhost:11434 \
  --http-model <model> --workload-file workloads/demo.json \
  --workers 4 --repeats 3 --mode both --evidence evidence/run.json
python -m armopt.select --evidence evidence/a.json --evidence evidence/b.json
```

## What this actually is

Three things, wired together, none of them faked:

1. **A benchmark harness** (`armopt.runner`) that runs an identical
   workload sequentially and through a persistent worker pool, against
   whichever `InferenceAdapter` you point it at, and reports latency,
   throughput, and wall time -- median of `--repeats` passes, with an
   untimed warmup.
2. **Signed evidence** (`armopt.evidence`) -- every run's inputs, outputs,
   platform, and a SHA256 over the whole payload, written atomically.
   `verify_evidence()` recomputes that hash and reports a match, a
   mismatch (edited after signing), or "not signed" -- this is not
   decorative; the interactive menu's `[4] Verify evidence` and the full
   pipeline both call it before trusting anything.
3. **A scheduler** (`armopt.scheduler` + `armopt.select`) that builds a
   `BackendProfile` from *measured* evidence files -- not hand-written
   numbers -- and picks a backend by a latency/cost/throughput score that
   is min-max normalized across the actual candidates being compared, so
   the weights mean what they claim to (see [Picking a backend](#picking-a-backend-from-measured-evidence)).

Nothing here assumes a specific runtime, model, or machine. `InferenceAdapter`
is a two-method protocol; `HttpAdapter` currently speaks Ollama and
llama-server, `JsonlAdapter` speaks anything over stdin/stdout JSON lines.

## What's been proven, with evidence

`examples/evidence/` is the full, real trail -- nothing here is illustrative
or synthetic:

- **Real Arm64 hardware, not claimed.** `.github/workflows/arm64-benchmark.yml`
  runs on a GitHub-hosted `ubuntu-24.04-arm` runner and fails outright if
  `uname -m` isn't `aarch64` before it will produce evidence.
- **Real AI runtimes, not a stub.** Ollama and llama-server, both actually
  installed/built in CI and queried over HTTP; the `--demo` adapter is used
  only to validate the harness itself and is labeled as such everywhere it
  appears, including in evidence files (`adapter: "demo-adapter"`).
- **A documented debugging trail, not a cherry-picked number.** The first
  concurrency measurement on Arm64 CI came back at 0.983x -- not a
  speedup. Two follow-up hypotheses (thread oversubscription, Ollama's own
  parallelism setting) were tested and ruled out with real runs before the
  actual cause was isolated: a scratch test proved this project's own
  HTTP client concurrency was sound (1.21s for 4 concurrent 1s calls vs a
  real 4.03s sequential), which meant the bottleneck was Ollama's server,
  not this code. Switching to llama-server's explicit `--parallel` slots
  then measured a real **1.39x**, with the latency/wall-time signature of
  genuine parallel execution rather than queuing. Every step is a
  committed evidence file:

  | Step | Config | Result | Status |
  |---|---|---|---|
  | 1 | Ollama, default threading | 0.983x | not a speedup |
  | 2 | Ollama, `num_thread=1` | 1.091x, 2x absolute wall time | hypothesis ruled out |
  | 3 | Ollama, `OLLAMA_NUM_PARALLEL=4` | 0.944x | hypothesis ruled out |
  | 4 | Ollama, both combined | 1.089x | same as step 2 |
  | 5 | `llama-server --parallel 4 -t 1` | **1.39x**, real contention signature | real, measured |

  Full narrative and the exact numbers: [What we actually found](#what-we-actually-found-on-a-free-arm64-runner).
- **A scheduler decision made from that evidence, not from a demo.**
  `examples/evidence/arm64_ci_selection_decision.json` is `armopt.select`'s
  real output from CI, choosing between the Ollama and llama-server runs
  above by measured aggregate throughput.
- **The full pipeline also runs outside CI, against a real user model.**
  `examples/evidence/local_x86_isyco_host_*.json` is `[6] Run full pipeline`
  executed on an ordinary x86_64 dev machine against a locally quantized
  model (not a runtime this project shipped) -- the menu honestly reports
  the host as non-Arm64 in the same summary rather than implying otherwise.
- **24 unit tests**, including a regression test for the scheduler's
  normalization bug and one that directly measures HTTP concurrency
  overlap instead of assuming it (`test_concurrent_calls_actually_overlap_in_wall_time`).

## How it works

```text
workload -> runtime adapter -> { sequential | dataflow } -> metrics -> evidence -> verify -> scheduler -> decision
```

Runtime adapters are supplied by the caller; the core carries no backend
name, machine path, or host assumption. `--mode both` runs the identical
workload through the same adapter twice: once sequentially (`workers=1`),
once through a reusable `DataflowSession` (`workers=N`, a persistent
`ThreadPoolExecutor`). The reported speedup is **the benefit of the
execution strategy** for whatever adapter is plugged in -- not a claim
that a runtime, model, or "DataFlow" itself made inference intrinsically
faster. Per-request latency can go *up* under concurrency (real contention)
while wall-clock time goes *down* -- that's the expected, honest result,
not a bug.

### Runtime adapters

**`HttpAdapter`** talks to Ollama's `/api/generate` (`--http-backend ollama`,
default) or llama-server's `/completion` (`--http-backend llama_server`).
Each call opens its own HTTP request with no adapter-side lock, so
concurrent callers reach the runtime concurrently -- this is directly
tested (`test_concurrent_calls_actually_overlap_in_wall_time`), not assumed.
Whether that turns into wall-clock speedup depends on the runtime's own
concurrency model; see the findings above.

**`JsonlAdapter`** connects a persistent external runtime over stdin/stdout:

```text
request  {"prompt": "...", "max_tokens": 64}
response {"text": "...", "input_tokens": 4, "output_tokens": 12}
```

It holds a single lock around each exchange, since a single persistent
subprocess is assumed to handle one request at a time. Use `HttpAdapter`
(or run several `JsonlAdapter` processes behind your own pool -- not
currently implemented, see Limitations) for concurrent inference.

## What we actually found on a free Arm64 runner

`examples/evidence/arm64_ci_step{1..5}_*.json` is the real diagnostic trail
from running this harness on a 4-vCPU GitHub-hosted Arm64 runner:

1. Ollama, default per-request threading, default `OLLAMA_NUM_PARALLEL` →
   **0.983x** ("speedup" that isn't one). Mean per-request latency nearly
   4x'd under concurrency while wall time didn't move.
2. Ollama, `num_thread=1` capped (hypothesis: core oversubscription) →
   **1.091x**, but *absolute* wall time roughly doubled. Ruled out.
3. Ollama, `OLLAMA_NUM_PARALLEL=4`, default threading (hypothesis: the
   server was serializing requests, fixable with its own concurrency
   setting) → **0.944x**. Also ruled out.
4. Ollama, `OLLAMA_NUM_PARALLEL=4` + `num_thread=1` → **1.089x**, same as
   step 2.

Neither lever moved the number, which meant the open question was: is this
box compute-saturated with no spare cycles for concurrency (a hardware
ceiling), or is Ollama itself just not overlapping requests on this CPU-only
build (a runtime limitation)? We isolated it directly: a scratch test ran
`HttpAdapter` against a `ThreadingHTTPServer` fixture that sleeps 1s per
request — 4 concurrent calls finished in **1.21s**, not ~4s (codified as
`test_concurrent_calls_actually_overlap_in_wall_time`). The client-side
concurrency mechanism was never the problem. Ollama's server was.

5. Swapped to `llama-server` (llama.cpp's own HTTP server, `--parallel 4
   -t 1` — four single-threaded slots exactly filling the 4 cores) →
   **1.39x**, and a different signature: wall time genuinely dropped
   (23.6s → 17.0s for 8 requests) while per-request latency rose from real
   CPU/memory contention between four simultaneous inferences, not queueing.
   That's what actual parallelism looks like on this hardware, and it's
   real, if modest — the ceiling is four cores each running one thread, not
   a marketing number.

Same workload, same model family, same signed-evidence pipeline, two
different HTTP runtimes — one that didn't deliver concurrency on this box
and one that did, both documented with real numbers instead of picking the
one that looked better.

## Picking a backend from measured evidence

`CostLatencyScheduler` (`armopt.scheduler`) scores candidate backends on
latency, cost, and throughput -- but scoring only means something if the
inputs are real and the units are comparable:

```bash
python -m armopt.select \
  --evidence evidence/ollama_run.json --evidence evidence/llama_server_run.json \
  --cost-per-1k-tokens 0.0 --cost-per-1k-tokens 0.0 \
  --latency-weight 1 --cost-weight 1 --throughput-weight 1
```

`armopt.select` builds one `BackendProfile` per evidence file from its
*measured* dataflow figures (`mean_latency_ms`, `tokens_per_second`) --
the same evidence `armopt.cli --evidence` already writes, not fabricated
numbers. The scheduler then min-max normalizes latency/cost/throughput
across the candidate set before weighting them: raw milliseconds and raw
dollars live on unrelated scales, and summing them unnormalized lets
whichever metric has the larger raw magnitude dominate the score
regardless of the weights (`test_high_cost_weight_actually_wins_when_units_differ_wildly`
in `test_scheduler.py` is the regression test for that bug).

The interactive menu's `[3] Run scheduler` and `[6] Run full pipeline`
sign the resulting decision through the same `write_evidence()` every
benchmark uses, so a decision is exactly as verifiable as a benchmark run
-- `[4] Verify evidence` works on either.

## Verifying evidence

```bash
python -m armopt.select --evidence a.json --evidence b.json   # produces a decision
python -c "from pathlib import Path; from armopt.evidence import verify_evidence; \
           print(verify_evidence(Path('evidence/run.json')))"
```

or from the menu: `[4] Verify evidence`. `verify_evidence()` recomputes the
SHA256 over the unsigned payload and compares it to the recorded
`evidence_sha256`. A mismatch means the file was edited after it was
written -- by hand, by a merge, or by anything else -- and is reported as
such, not silently trusted.

## Arm64 CI evidence

`.github/workflows/arm64-benchmark.yml` runs the full benchmark on a
GitHub-hosted `ubuntu-24.04-arm` runner (Arm64 silicon, free for public
repos, no cloud account needed): installs Ollama and pulls a small model,
builds `llama-server` from source, runs `armopt.cli` against both over
`HttpAdapter`, runs `armopt.select` over the resulting evidence, and
uploads every signed JSON as a workflow artifact. The job fails outright if
`uname -m` isn't `aarch64`, so a passing run is proof the numbers came
from real Arm64 hardware, not an x86 host claiming otherwise.

## Limitations

What this project has **not** demonstrated, stated plainly instead of
implied away:

- **CPU only.** No GPU/NPU runtime (CUDA, Metal, an Arm NPU delegate) has
  been benchmarked. The 1.39x concurrency result is CPU-bound inference on
  a specific 4-vCPU runner; it is not a general claim about Arm64 AI
  performance.
- **One small model family per run.** Measurements use `qwen2.5:0.5b` /
  `qwen2.5-0.5b-instruct-q4_k_m` (CI) or whatever model the operator points
  the menu at locally. Behavior at larger model sizes or different
  architectures is untested.
- **Small workload, single measurement window.** `workloads/demo.json` is
  8 prompts; `--repeats` takes a median across passes but this is not a
  sustained-load or production-traffic benchmark.
- **Cost is always 0.0 in every real run so far.** Every runtime measured
  has been local and free; the scheduler's cost dimension is exercised by
  a unit test with synthetic numbers (`test_high_cost_weight_actually_wins_when_units_differ_wildly`),
  not by a real paid backend.
- **`JsonlAdapter` concurrency is architectural, not benchmarked.** It's
  documented as one-request-at-a-time by design; running several
  `JsonlAdapter` processes behind a pool for real concurrent throughput is
  suggested but not implemented or measured here.
- **Only two providers known to the menu.** `[2] Compare providers` and
  `[6] Run full pipeline` currently detect Ollama and llama-server only;
  other runtimes (ONNX Runtime, ExecuTorch, vLLM, etc.) would need their
  own `InferenceAdapter` and provider entry.
- **The interactive menu's `input()`-driven flows are smoke-tested
  manually**, not under automated test; the pure logic behind them
  (evidence discovery, reachability checks, the full benchmark→evidence→
  verify→scheduler→decision chain) is covered by `tests/test_menu.py`
  using the demo adapter.

## Tests

```bash
python -m pytest tests/ -q
```

24 tests across contracts, the runner, both adapters, the scheduler
(including the normalization regression test), evidence signing/verification,
and the menu's discovery/pipeline logic.

## License

MIT. See `LICENSE`.
