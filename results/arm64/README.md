# Arm64 Benchmark Results

Measured on a GitHub-hosted `ubuntu-24.04-arm` runner. The workflow asserts
`uname -m == aarch64` before producing anything, so these numbers cannot come
from an x86 host.

- **Platform**: `Linux-6.17.0-1022-azure-aarch64-with-glibc2.39`
- **Host**: 4 vCPU, 0xd49 (recorded by the runner in `evidence/arm64_ci/host.json`)
- **Python**: 3.12.13
- **Model**: qwen2.5-0.5b-instruct
- **Workload**: 8 requests, 3 repeats, 4 workers in dataflow mode
- **Measured**: 2026-08-14T13:40:14.705502+00:00

## Measured configurations

| Configuration | Sequential | Dataflow | Wall-time speedup | tokens/s |
|---|---|---|---|---|
| Ollama, default per-request threading (OLLAMA_NUM_PARALLEL=4) | 10.09s | 10.35s | **0.975x** | 50.7 -> 49.5 |
| Ollama, capped per-request threading (num_thread=1) | 22.54s | 20.68s | **1.09x** | 22.7 -> 24.8 |
| llama-server, --parallel 4 -t 1 | 23.32s | 17.02s | **1.37x** | 21.8 -> 30.1 |

**Best wall-time speedup**: 1.37x (llama-server, --parallel 4 -t 1).

## Scheduler decision

The scheduler selected: **`http:ollama:qwen2.5:0.5b`**

It optimizes for mean latency and throughput, not wall-time speedup. The
configuration with the best wall-time speedup is not the one it deploys --
see the repository README for why that disagreement is the point.

## Evidence integrity

| File | evidence_sha256 |
|---|---|
| `evidence/arm64_ci/arm64_naive.json` | `4bff23bff0683369...` |
| `evidence/arm64_ci/arm64_capped.json` | `dfc6312263ab40e9...` |
| `evidence/arm64_ci/arm64_llama_server.json` | `e20e0d59ee56a566...` |

Verify any of them:

```bash
python -c "from pathlib import Path; from armopt.evidence import verify_evidence; \
print(verify_evidence(Path('evidence/arm64_ci/arm64_llama_server.json')))"
```

Regenerate this directory from the evidence:

```bash
python scripts/build_arm64_results.py
```
