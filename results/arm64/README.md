# Arm64 Benchmark Results

**Generated**: 2026-08-13T23:32:01.417279+00:00

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
| Total Time | 0.15s | 0.09s | **1.662×** |
| p50 Latency | 1.5ms | 3.2ms | **0.464×** |
| p95 Latency | 1.6ms | 1.7ms | **0.962×** |
| Throughput | 662.37 req/s | 1100.69 req/s | **1.662×** |
| Tokens/sec | 1987 | 3302 | **1.662×** |

## Evidence Integrity

| File | SHA256 |
|------|--------|
| arm64_sequential.json | 2ff4557a0a836ae9343c628947d632042aa366c4dff3b9d758a6b12972dad774 |
| arm64_dataflow.json | 8e74dafeb3d384b6fa71ad5b6dea07aa033a1f8f0770ff57483039e51f8a4267 |

Verify with:
```bash
python -c "from pathlib import Path; from armopt.evidence import verify_evidence; print(verify_evidence(Path('results/arm64/arm64_sequential.json')))"
```
