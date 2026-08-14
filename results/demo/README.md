# Demo Harness Benchmark Results

These numbers come from the in-memory demo adapter on the machine named below.
They exercise the harness, not an AI runtime, and say nothing about Arm64
performance. For Arm64 measurements see `results/arm64/`.

**Generated**: 2026-08-14T09:24:10.931336+00:00

## Platform
- Architecture: AMD64
- OS: Windows 11
- CPU: AMD64 Family 25 Model 117 Stepping 2, AuthenticAMD
- Python: 3.12.4

## Runtime
- Name: demo-adapter
- Config: in-memory demo (no external runtime)

## Model
- Name: demo-model

## Workload
- Requests: 100
- Workers: 4
- Repeats: 3

## Metrics

| Metric | Baseline (sequential) | Optimized (dataflow) | Speedup |
|--------|----------------------|---------------------|---------|
| Total Time | 0.15s | 0.04s | **3.692×** |
| p50 Latency | 1.5ms | 1.5ms | **1.001×** |
| p95 Latency | 1.7ms | 1.6ms | **1.03×** |
| Throughput | 657.14 req/s | 2426.07 req/s | **3.692×** |
| Tokens/sec | 1971 | 7278 | **3.692×** |

## Evidence Integrity

| File | SHA256 |
|------|--------|
| demo_sequential.json | bb44bc85725d47764a40c0c8f059f24c659dde2901b72e73f26ca70c42f50678 |
| demo_dataflow.json | b1fb64e7679a5edb6b5abd9a276b2fc36e9917ff4954a74d491d734f19a6c32d |

Verify with:
```bash
python -c "from pathlib import Path; from armopt.evidence import verify_evidence; print(verify_evidence(Path('results/demo/demo_sequential.json')))"
```
