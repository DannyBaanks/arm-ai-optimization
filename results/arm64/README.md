# Arm64 Benchmark Results

Measured on a GitHub-hosted `ubuntu-24.04-arm` runner. The workflow asserts
`uname -m == aarch64` before producing anything, so these numbers cannot come
from an x86 host.

- **Platform**: `Linux-6.17.0-1022-azure-aarch64-with-glibc2.39`
- **Host**: 4 vCPU, 0xd49 (recorded by the runner in `evidence/arm64_ci/host.json`)
- **Python**: 3.12.13
- **Model**: qwen2.5-0.5b-instruct
- **Workload**: 8 requests, 3 repeats, 4 workers in dataflow mode
- **Measured**: 2026-08-14T19:06:38.954609+00:00

## Measured configurations

| Configuration | Sequential | Dataflow | Wall-time speedup | tokens/s |
|---|---|---|---|---|
| Ollama, default per-request threading (OLLAMA_NUM_PARALLEL=4) | 10.60s | 11.03s | **0.961x** | 48.3 -> 46.4 |
| Ollama, capped per-request threading (num_thread=1) | 22.78s | 20.75s | **1.098x** | 22.5 -> 24.7 |
| llama-server, --parallel 4 -t 1 | 23.15s | 16.96s | **1.365x** | 22.1 -> 30.2 |

**Best wall-time speedup**: 1.365x (llama-server, --parallel 4 -t 1).

## Scheduler decision

The scheduler selected: **`http:ollama:qwen2.5:0.5b`**

It optimizes for mean latency and throughput, not wall-time speedup. The
configuration with the best wall-time speedup is not the one it deploys --
see the repository README for why that disagreement is the point.

## Evidence integrity

| File | evidence_sha256 |
|---|---|
| `evidence/arm64_ci/arm64_naive.json` | `380df1f9a3d1aa17...` |
| `evidence/arm64_ci/arm64_capped.json` | `da8162f0985ece56...` |
| `evidence/arm64_ci/arm64_llama_server.json` | `1a8931995b931548...` |

Verify any of them:

```bash
python -c "from pathlib import Path; from armopt.evidence import verify_evidence; \
print(verify_evidence(Path('evidence/arm64_ci/arm64_llama_server.json')))"
```

Regenerate this directory from the evidence:

```bash
python scripts/build_arm64_results.py
```
