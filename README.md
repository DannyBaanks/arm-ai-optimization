# Arm AI Optimization Harness

Portable benchmark harness for comparing AI inference execution strategies
on Arm64 and other CPU platforms, with an HTTP adapter wired to a real
runtime and signed evidence written on every run.

The project keeps the workload, runtime adapter, execution mode, and metrics
behind small public contracts. No backend name, machine path, or host
assumption is embedded in the core.

## Quick Start (harness smoke test, no AI runtime needed)

```powershell
python -m venv .venv
python -m pip install -e .
python -m armopt.cli --demo --requests 32 --workers 4 --mode both
```

The demo adapter is deterministic and only validates the harness. It is not
an AI performance result.

## Real run, against an Ollama-compatible runtime

```bash
python -m armopt.cli \
  --adapter http --http-url http://localhost:11434 --http-model <your-model> \
  --workload-file workloads/demo.json \
  --workers 4 --repeats 3 --mode both \
  --evidence evidence/run.json --workload-id demo
```

`--repeats` reruns each mode and reports the median wall time, so one lucky
or unlucky pass doesn't decide the headline number. `--warmup` (default 1)
sends untimed requests first to absorb model-load/first-token cost before
the timed pass starts. `--evidence` writes a SHA256-signed JSON with the
full result plus platform metadata (see `examples/evidence/schema_example.json`
for a real run's shape).

## What the comparison actually measures

`--mode both` runs the identical workload through the same adapter twice:
once sequentially (`workers=1`), once through a reusable `DataflowSession`
(`workers=N`, a persistent `ThreadPoolExecutor`). The reported speedup is
**the benefit of the execution strategy** — reusing a persistent worker
pool instead of issuing requests one at a time — for whatever adapter is
plugged in. It is not a claim that any particular runtime, model, or
"DataFlow" itself made inference intrinsically faster. With a real runtime,
per-request latency can actually go *up* under concurrency (real CPU
contention) while wall-clock time still goes *down* — that's expected and
is the honest result, not a bug.

## Design

```text
workload -> runtime adapter -> { sequential | dataflow } -> metrics -> evidence
```

Runtime adapters are loaded explicitly by the application. Filesystem paths are
passed as arguments or resolved relative to the current project; the core does
not contain machine-specific paths.

## Runtime Adapters

Two interchangeable adapters implement the same `InferenceAdapter` protocol:

**`HttpAdapter`** talks to Ollama's `/api/generate` (`--http-backend ollama`,
default) or llama-server's `/completion` (`--http-backend llama_server`).
Each call opens its own HTTP request with no adapter-side lock, so
concurrent callers reach the runtime concurrently — `ThreadPoolExecutor`
workers overlap in the runtime itself, not just in Python (this is
directly tested, not assumed — see `test_http_adapter.py`). Whether that
turns into wall-clock speedup depends on the runtime's own concurrency
model; see the findings below.

**`JsonlAdapter`** connects a persistent external runtime over stdin/stdout
without coupling the harness to its implementation:

```text
request  {"prompt": "...", "max_tokens": 64}
response {"text": "...", "input_tokens": 4, "output_tokens": 12}
```

It holds a single lock around each request/response exchange, since a
single persistent subprocess is assumed to handle one request at a time.
Use `HttpAdapter` (or run several `JsonlAdapter` processes behind your own
pool) when you need true concurrent inference.

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

## Arm64 CI evidence

`.github/workflows/arm64-benchmark.yml` runs the full benchmark on a
GitHub-hosted `ubuntu-24.04-arm` runner (Arm64 silicon, free for public
repos, no cloud account needed): installs Ollama and pulls a small model,
builds `llama-server` from source, runs `armopt.cli` against both over
`HttpAdapter`, and uploads every signed evidence JSON as a workflow
artifact. The job fails outright if `uname -m` isn't `aarch64`, so a
passing run is proof the numbers came from real Arm64 hardware, not an x86
host claiming otherwise.

## License

MIT. See `LICENSE`.
