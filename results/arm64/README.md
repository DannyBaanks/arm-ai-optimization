# Arm64 Benchmark Results

Measured on a GitHub-hosted `ubuntu-24.04-arm` runner. The workflow asserts
`uname -m == aarch64` before producing anything, so these numbers cannot come
from an x86 host.

- **Platform**: `Linux-6.17.0-1022-azure-aarch64-with-glibc2.39`
- **Host**: core count and silicon not yet captured; the next CI run records them to `evidence/arm64_ci/host.json`
- **Python**: 3.12.13
- **Model**: qwen2.5-0.5b-instruct
- **Workload**: 8 requests, 3 repeats, 4 workers in dataflow mode
- **Measured**: 2026-08-14T05:35:55.729784+00:00

## Measured configurations

| Configuration | Sequential | Dataflow | Wall-time speedup | tokens/s |
|---|---|---|---|---|
| Ollama, default per-request threading (OLLAMA_NUM_PARALLEL=4) | 9.68s | 10.13s | **0.955x** | 52.9 -> 50.5 |
| Ollama, capped per-request threading (num_thread=1) | 21.99s | 20.50s | **1.072x** | 22.1 -> 25.0 |
| llama-server, --parallel 4 -t 1 | 23.26s | 16.88s | **1.378x** | 22.0 -> 30.3 |

**Best wall-time speedup**: 1.378x (llama-server, --parallel 4 -t 1).

## Scheduler decision

The scheduler selected: **`http:ollama:qwen2.5:0.5b`**

It optimizes for mean latency and throughput, not wall-time speedup. The
configuration with the best wall-time speedup is not the one it deploys --
see the repository README for why that disagreement is the point.

## Evidence integrity

| File | evidence_sha256 |
|---|---|
| `evidence/arm64_ci/arm64_naive.json` | `d634f0ddb20e5250...` |
| `evidence/arm64_ci/arm64_capped.json` | `9befa97b241c5f0b...` |
| `evidence/arm64_ci/arm64_llama_server.json` | `d17a4c5e0e4c1d61...` |

Verify any of them:

```bash
python -c "from pathlib import Path; from armopt.evidence import verify_evidence; \
print(verify_evidence(Path('evidence/arm64_ci/arm64_llama_server.json')))"
```

Regenerate this directory from the evidence:

```bash
python scripts/build_arm64_results.py
```
