"""Interactive menu: a thin UX layer over the existing benchmark CLI,
scheduler, and evidence pipeline.

Every action below calls `armopt.cli.run`, `armopt.select.run`,
`armopt.evidence.write_evidence`/`verify_evidence` -- the exact same
functions the `armopt` / `armopt-select` console scripts call. Nothing
here is a second implementation, and nothing here fabricates a result:
if a real runtime isn't reachable, the affected actions say so and stop
instead of substituting a mock.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import cli as armopt_cli
from . import select as armopt_select
from .evidence import verify_evidence, write_evidence

EVIDENCE_DIRS = [Path("evidence"), Path("examples/evidence")]
DEFAULT_WORKLOAD = Path("workloads/demo.json")


@dataclass(frozen=True)
class Provider:
    label: str
    backend: str  # "ollama" | "llama_server"
    url: str
    health_path: str


KNOWN_PROVIDERS = [
    Provider("Ollama", "ollama", "http://localhost:11434", "/api/tags"),
    Provider("llama-server", "llama_server", "http://127.0.0.1:8081", "/health"),
]


# --- pure/testable helpers -------------------------------------------------

def is_reachable(provider: Provider, timeout: float = 1.5) -> bool:
    try:
        urllib.request.urlopen(provider.url.rstrip("/") + provider.health_path, timeout=timeout)
        return True
    except (urllib.error.URLError, OSError):
        return False


def ollama_models(url: str, timeout: float = 2.0) -> list[str]:
    """Real models actually pulled on this Ollama instance -- never a
    guessed or hardcoded list."""
    try:
        request = urllib.request.Request(url.rstrip("/") + "/api/tags")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
        return [model["name"] for model in payload.get("models", [])]
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
        return []


def _load_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def discover_evidence(dirs: list[Path] = EVIDENCE_DIRS) -> list[Path]:
    """Signed evidence files (schema + evidence_sha256 present) across the
    known locations, newest first. Raw stdout captures and unrelated JSON
    are excluded -- this only surfaces what verify_evidence can check."""
    found: list[Path] = []
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            payload = _load_json(path)
            if payload is not None and "evidence_sha256" in payload:
                found.append(path)
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def is_decision(payload: dict) -> bool:
    """True for evidence files whose results are a scheduler decision
    (armopt.select's output written through write_evidence) rather than a
    benchmark result."""
    results = payload.get("results")
    return isinstance(results, dict) and "selected" in results and "candidates" in results


def discover_decisions(dirs: list[Path] = EVIDENCE_DIRS) -> list[Path]:
    return [p for p in discover_evidence(dirs) if is_decision(_load_json(p) or {})]


def system_status() -> dict[str, object]:
    """Everything option [7] reports, also reused by the full-pipeline
    summary so both tell the same truth about the host actually running."""
    machine = platform.machine()
    return {
        "platform": platform.platform(),
        "machine": machine,
        "is_arm64": machine.lower() in ("aarch64", "arm64"),
        "python": sys.version.split()[0],
        "providers": {p.label: is_reachable(p) for p in KNOWN_PROVIDERS},
        "evidence_files": len(discover_evidence()),
    }


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# --- small input helpers ----------------------------------------------------

def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def _ask_int(prompt: str, default: int) -> int:
    raw = _ask(prompt, str(default))
    try:
        return int(raw)
    except ValueError:
        print(f"  '{raw}' is not a number, using {default}")
        return default


def _ask_choice(prompt: str, options: list[str]) -> str | None:
    if not options:
        return None
    for index, option in enumerate(options, start=1):
        print(f"  [{index}] {option}")
    raw = _ask(prompt, "1")
    try:
        index = int(raw)
        if 1 <= index <= len(options):
            return options[index - 1]
    except ValueError:
        pass
    print(f"  '{raw}' is not one of the listed options")
    return None


# --- actions -----------------------------------------------------------------

def _run_one_benchmark(*, adapter: str, http_url: str | None, http_model: str | None,
                        http_backend: str, workers: int, repeats: int,
                        evidence_path: Path) -> dict:
    """Build the same argv `armopt` would take on the command line and run
    it through the one real implementation (armopt.cli.run)."""
    argv = ["--adapter", "demo" if adapter == "demo" else "http",
            "--workload-file", str(DEFAULT_WORKLOAD),
            "--workers", str(workers), "--repeats", str(repeats), "--mode", "both",
            "--evidence", str(evidence_path), "--workload-id", "menu-run"]
    if adapter != "demo":
        argv += ["--http-url", http_url, "--http-model", http_model, "--http-backend", http_backend]
    print(f"  RUNNING benchmark ({adapter}, workers={workers}, repeats={repeats})...")
    try:
        outcome = armopt_cli.run(argv)
    except Exception as exc:  # noqa: BLE001 -- surface any adapter/runtime failure to the user
        print(f"  FAIL: {exc}")
        raise
    print(f"  PASS -- evidence written to {outcome['evidence_path']}")
    return outcome


def action_run_benchmark() -> None:
    print("\n== Run benchmark ==")
    reachable = {p.label: is_reachable(p) for p in KNOWN_PROVIDERS}
    options = ["demo (harness smoke test -- NOT an AI performance result)"]
    options += [f"{p.label} ({p.url}) [{'reachable' if reachable[p.label] else 'NOT reachable now'}]"
                for p in KNOWN_PROVIDERS]
    choice = _ask_choice("Provider", options)
    if choice is None:
        return

    workers = _ask_int("Workers", 4)
    repeats = _ask_int("Repeats", 3)
    evidence_path = Path("evidence") / f"menu_run_{_timestamp()}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)

    if choice.startswith("demo"):
        _run_one_benchmark(adapter="demo", http_url=None, http_model=None, http_backend="ollama",
                            workers=workers, repeats=repeats, evidence_path=evidence_path)
        return

    provider = next(p for p in KNOWN_PROVIDERS if choice.startswith(p.label))
    if not reachable[provider.label]:
        print(f"  {provider.label} is not reachable at {provider.url} right now -- "
              "start it and try again. Not substituting a mock result.")
        return

    model = provider.label
    if provider.backend == "ollama":
        models = ollama_models(provider.url)
        if not models:
            print("  No models found on this Ollama instance -- pull one first.")
            return
        picked = _ask_choice("Model", models)
        if picked is None:
            return
        model = picked
    else:
        model = _ask("Label for the already-loaded llama-server model", "llama-server-model")

    _run_one_benchmark(adapter="http", http_url=provider.url, http_model=model,
                        http_backend=provider.backend, workers=workers, repeats=repeats,
                        evidence_path=evidence_path)


def action_compare_providers() -> list[Path]:
    print("\n== Compare providers ==")
    reachable = [p for p in KNOWN_PROVIDERS if is_reachable(p)]
    if len(reachable) < 2:
        names = ", ".join(p.label for p in reachable) or "none"
        print(f"  Only {len(reachable)} provider(s) reachable ({names}). "
              "A meaningful comparison needs at least 2 running at once.")
        if not reachable:
            return []
        if _ask("Continue with just what's available? (y/n)", "n").lower() != "y":
            return []

    workers = _ask_int("Workers", 4)
    repeats = _ask_int("Repeats", 3)
    written: list[Path] = []
    for provider in reachable:
        model = provider.label
        if provider.backend == "ollama":
            models = ollama_models(provider.url)
            if not models:
                print(f"  Skipping {provider.label}: no models pulled.")
                continue
            model = models[0]
            print(f"  Using {provider.label} model: {model}")
        else:
            model = _ask(f"Label for the model loaded on {provider.label}", "llama-server-model")
        path = Path("evidence") / f"compare_{provider.backend}_{_timestamp()}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        outcome = _run_one_benchmark(adapter="http", http_url=provider.url, http_model=model,
                                      http_backend=provider.backend, workers=workers,
                                      repeats=repeats, evidence_path=path)
        written.append(outcome["evidence_path"])

    if written:
        print("\n  Measured (dataflow figures):")
        for path in written:
            payload = _load_json(path) or {}
            dataflow = payload.get("results", {}).get("dataflow", {})
            print(f"    {payload.get('adapter')}: "
                  f"{dataflow.get('mean_latency_ms')} ms mean, "
                  f"{dataflow.get('tokens_per_second')} tok/s")
    return written


def action_run_scheduler(evidence_paths: list[Path] | None = None) -> Path | None:
    print("\n== Run scheduler ==")
    candidates = discover_evidence()
    candidates = [p for p in candidates if not is_decision(_load_json(p) or {})]
    if evidence_paths is None:
        if not candidates:
            print("  No benchmark evidence found yet -- run a benchmark first (option 1 or 2).")
            return None
        print("  Evidence available:")
        for index, path in enumerate(candidates, start=1):
            print(f"    [{index}] {path}")
        raw = _ask("Pick evidence numbers to compare, comma-separated", "all")
        if raw.strip().lower() == "all":
            evidence_paths = candidates
        else:
            try:
                indices = [int(token) for token in raw.split(",") if token.strip()]
                evidence_paths = [candidates[i - 1] for i in indices]
            except (ValueError, IndexError):
                print(f"  Could not parse '{raw}'.")
                return None

    if len(evidence_paths) < 1:
        print("  Need at least one evidence file.")
        return None

    argv = []
    for path in evidence_paths:
        argv += ["--evidence", str(path)]
    decision = armopt_select.run(argv)

    decision_path = Path("evidence") / f"selection_{_timestamp()}.json"
    write_evidence(decision_path, results=decision, workload_id="scheduler-selection",
                    adapter=decision["selected"])
    print(f"  Selected: {decision['selected']}")
    print(f"  Reason:   {decision['reason']}")
    print(f"  Decision written to {decision_path}")
    return decision_path


def action_verify_evidence() -> None:
    print("\n== Verify evidence ==")
    files = discover_evidence()
    if not files:
        print("  No evidence files found.")
        return
    print("  [0] all")
    for index, path in enumerate(files, start=1):
        print(f"  [{index}] {path}")
    raw = _ask("Pick a file to verify", "0")
    try:
        picked = files if raw.strip() == "0" else [files[int(raw) - 1]]
    except (ValueError, IndexError):
        print(f"  '{raw}' is not a valid choice.")
        return
    for path in picked:
        ok, message = verify_evidence(path)
        status = "EVIDENCE VERIFIED" if ok else "EVIDENCE TAMPERED/INVALID"
        print(f"  {status}: {path}")
        print(f"    {message}")


def action_show_latest_decision() -> None:
    print("\n== Latest decision ==")
    decisions = discover_decisions()
    if not decisions:
        print("  No scheduler decisions yet -- run option [3] first.")
        return
    payload = _load_json(decisions[0]) or {}
    results = payload.get("results", {})
    print(f"  From: {decisions[0]} (created {payload.get('created_at')})")
    print("  Candidates:")
    for candidate in results.get("candidates", []):
        print(f"    - {candidate['adapter']}: {candidate['mean_latency_ms']} ms mean, "
              f"{candidate['output_tokens_per_second']} tok/s, "
              f"${candidate['cost_per_1k_tokens']}/1k tokens")
    print(f"  Selected: {results.get('selected')}")
    print(f"  Reason:   {results.get('reason')}")
    print(f"  Measured on: {payload.get('platform')}")


def action_system_status(run_tests: bool = True) -> dict[str, object]:
    print("\n== System status ==")
    status = system_status()
    arm_flag = "yes" if status["is_arm64"] else "NO -- x86_64/other; Arm64 claims need CI or a real Arm64 host"
    print(f"  Platform:      {status['platform']}")
    print(f"  Architecture:  {status['machine']} (Arm64: {arm_flag})")
    print(f"  Python:        {status['python']}")
    print("  Providers:")
    for label, up in status["providers"].items():
        print(f"    [{'UP' if up else 'down'}] {label}")
    print(f"  Evidence files on disk: {status['evidence_files']}")
    if run_tests:
        result = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                                 capture_output=True, text=True)
        print(f"  Test suite: {'PASS' if result.returncode == 0 else 'FAIL'} "
              f"({result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ''})")
    return status


def action_full_pipeline() -> None:
    print("\n== Full pipeline: benchmark -> evidence -> verification -> scheduler -> decision ==")
    status = action_system_status(run_tests=False)

    evidence_paths = action_compare_providers()
    if not evidence_paths:
        print("\n  No real provider was reachable, so there is nothing honest to hand the "
              "scheduler. Start Ollama and/or llama-server and run this again.")
        print("  (A demo-adapter run is available separately via option [1], but it is not "
              "an AI performance result and this pipeline will not present it as one.)")
        return

    print("\n  -- Verification --")
    all_ok = True
    for path in evidence_paths:
        ok, message = verify_evidence(path)
        print(f"  {'EVIDENCE VERIFIED' if ok else 'EVIDENCE TAMPERED/INVALID'}: {path}")
        all_ok = all_ok and ok
    if not all_ok:
        print("  Stopping: not all evidence verified. Not handing unverified data to the scheduler.")
        return

    decision_path = action_run_scheduler(evidence_paths)
    if decision_path is None:
        return
    decision_payload = (_load_json(decision_path) or {}).get("results", {})

    print("\n  ---- Summary ----")
    print(f"  {'✓' if status['is_arm64'] else '⚠'} "
          f"{'ARM64 hardware detected' if status['is_arm64'] else 'Running on ' + status['machine'] + ', not Arm64'}")
    print(f"  ✓ {len(evidence_paths)} provider(s) evaluated")
    print("  ✓ Real benchmark completed")
    print("  ✓ Evidence verified")
    print("  ✓ Scheduler decision produced")
    print(f"\n  Selected provider:\n    {decision_payload.get('selected')}")
    print(f"\n  Reason:\n    {decision_payload.get('reason')}")
    print("\n  Evidence:")
    for path in evidence_paths:
        print(f"    {path}")
    print(f"    {decision_path}")
    print("\n  Limitations:")
    print("    - Single measurement window on one host; not a claim about production load.")
    print("    - Cost is 0.0 for all local runtimes here (no billing signal available).")
    if not status["is_arm64"]:
        print("    - This host is not Arm64 -- see .github/workflows/arm64-benchmark.yml "
              "and examples/evidence/arm64_ci_step*.json for the real Arm64 measurements.")


MENU_TEXT = """
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
"""

ACTIONS = {
    "1": action_run_benchmark,
    "2": action_compare_providers,
    "3": action_run_scheduler,
    "4": action_verify_evidence,
    "5": action_show_latest_decision,
    "6": action_full_pipeline,
    "7": action_system_status,
}


def main() -> int:
    # Windows consoles/redirected output don't always default to UTF-8;
    # without this, the checkmarks below raise UnicodeEncodeError instead
    # of printing (found by actually running this, not assumed safe).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    while True:
        print(MENU_TEXT)
        try:
            choice = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice == "0":
            return 0
        action = ACTIONS.get(choice)
        if action is None:
            print(f"'{choice}' is not a valid option.")
            continue
        try:
            action()
        except Exception as exc:  # noqa: BLE001 -- keep the menu alive, report the failure plainly
            print(f"  FAILED: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
