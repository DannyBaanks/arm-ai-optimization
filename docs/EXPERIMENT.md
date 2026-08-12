# Arm Inference Experiment

## Question

Does persistent Dataflow execution improve useful inference throughput on an
Arm64 CPU while keeping the model, runtime, prompts, and generation settings
constant?

## Hypotheses

- **H0:** Dataflow does not produce a meaningful improvement over the
  sequential baseline.
- **H1:** Dataflow improves throughput and/or tail latency under the selected
  workload without changing output correctness.

## Primary Metric

`output_tokens / wall_second`

## Secondary Metrics

- p50 request latency
- p95 request latency
- requests per second
- CPU utilization
- peak resident memory
- estimated cost per 1,000 output tokens
- output equivalence against the baseline

## Controlled Variables

- Same Arm64 host and CPU allocation.
- Same model artifact and checksum.
- Same runtime version and runtime flags.
- Same prompt file and prompt order.
- Same generation parameters.
- Same warmup policy.
- Same repetition count.

Only the execution mode changes between baseline and Dataflow.

## Required Evidence

An experiment is complete only when it contains:

1. Runtime and model identifiers.
2. Host architecture and resource allocation.
3. Workload checksum.
4. Baseline and Dataflow raw results.
5. At least three measured repetitions per mode.
6. p50, p95, throughput, token, CPU, memory, and cost metrics where
   available.
7. Output-equivalence results.
8. A reproducible command from a clean checkout.

## Success Gate

Proceed to final presentation only if:

- outputs are equivalent;
- the benchmark is reproducible;
- the primary metric improves by at least 10%, or the experiment documents a
  clear latency/cost trade-off with measured evidence;
- no uncontrolled machine-specific path or credential is required.

Otherwise, report the result as a valid negative experiment and do not claim
an optimization.
