# Arm AI Optimization Harness

Portable benchmark harness for comparing AI inference execution modes on Arm64
and other CPU platforms.

The project keeps the workload, runtime adapter, execution mode, and metrics
behind small public contracts. No backend name, machine path, or host
assumption is embedded in the core.

## Quick Start

```powershell
python -m venv .venv
python -m pip install -e .
python -m armopt.cli --demo --requests 32 --workers 4 --mode both
```

The demo adapter is deterministic and only validates the harness. It is not
an AI performance result. Real submissions should add an adapter for an AI
runtime and report measurements from an Arm64 host.

`--mode both` runs the same workload sequentially and through a reusable
Dataflow session, then reports wall-time speedup. The comparison is fair:
both modes use the same adapter, prompts, and output contract.

## Design

```text
workload -> runtime adapter -> { sequential | dataflow } -> metrics -> evidence
```

Runtime adapters are loaded explicitly by the application. Filesystem paths are
passed as arguments or resolved relative to the current project; the core does
not contain machine-specific paths.

## Runtime Adapter

`JsonlAdapter` connects a persistent external runtime without coupling the
harness to its implementation. The command is supplied by the caller and
must use this protocol:

```text
request  {"prompt": "...", "max_tokens": 64}
response {"text": "...", "input_tokens": 4, "output_tokens": 12}
```

This allows the same harness to benchmark a local process, an Arm64 runtime,
or a remote service while keeping runtime-specific code outside the core.

## License

MIT. See `LICENSE`.
