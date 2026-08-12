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

**`HttpAdapter`** talks to an Ollama-compatible `/api/generate` endpoint.
Each call opens its own HTTP request with no adapter-side lock, so
concurrent callers reach the runtime concurrently — `ThreadPoolExecutor`
workers overlap in the runtime itself, not just in Python.

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

## Arm64 CI evidence

`.github/workflows/arm64-benchmark.yml` runs the full benchmark on a
GitHub-hosted `ubuntu-24.04-arm` runner (Arm64 silicon, free for public
repos, no cloud account needed): installs Ollama, pulls a small model,
runs `armopt.cli` against it over `HttpAdapter`, and uploads the signed
evidence JSON as a workflow artifact. The job fails outright if
`uname -m` isn't `aarch64`, so a passing run is proof the numbers came
from real Arm64 hardware, not an x86 host claiming otherwise.

## License

MIT. See `LICENSE`.
