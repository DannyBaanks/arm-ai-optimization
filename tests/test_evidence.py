from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from armopt.evidence import canonical_hash, verify_evidence, write_evidence


class EvidenceTests(unittest.TestCase):
    def test_freshly_written_evidence_verifies(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.json"
            write_evidence(path, results={"speedup_wall": 1.39}, workload_id="demo",
                            adapter="http:llama_server:x")
            ok, message = verify_evidence(path)
        self.assertTrue(ok, message)
        self.assertIn("matches", message)

    def test_edited_evidence_fails_verification(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.json"
            write_evidence(path, results={"speedup_wall": 1.39}, workload_id="demo",
                            adapter="http:llama_server:x")
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["results"]["speedup_wall"] = 9.99  # tamper after signing
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            ok, message = verify_evidence(path)
        self.assertFalse(ok)
        self.assertIn("MISMATCH", message)

    def test_file_without_a_signature_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "unsigned.json"
            path.write_text(json.dumps({"results": {}}), encoding="utf-8")
            ok, message = verify_evidence(path)
        self.assertFalse(ok)
        self.assertIn("no evidence_sha256", message)

    def test_missing_file_is_reported_not_raised(self) -> None:
        ok, message = verify_evidence(Path("does/not/exist.json"))
        self.assertFalse(ok)
        self.assertIn("could not read", message)

    #: Files under an evidence directory that are deliberately not signed
    #: evidence. Each entry needs a reason: an undeclared exception is
    #: indistinguishable from a file that quietly stopped verifying.
    UNSIGNED_ARTIFACTS = {
        "arm64_ci_selection_decision.json":
            "scheduler decision, not evidence -- armopt.select prints to stdout "
            "and CI redirects it to a file, so it never passes through a signer",
    }

    def test_evidence_directories_all_verify(self) -> None:
        """Every signed file under an evidence directory must verify.

        Regression test. Three scripts had each re-implemented the signing
        scheme instead of importing it, and two had drifted -- one omitted
        ``separators``, one hashed an empty ``evidence_sha256`` placeholder.
        Both shipped files that ``verify_evidence()`` rejected, and both backed
        README claims (COBOL engine, Malbolge 4/4).

        ``examples/evidence`` is the set a judge actually gets: ``evidence/``
        is gitignored as a local scratch directory, so testing only that one
        would check exactly the files nobody else can see.
        """
        root = Path(__file__).resolve().parent.parent
        files = sorted(
            path
            for directory in ("evidence", "examples/evidence")
            for path in (root / directory).glob("*.json")
        )
        self.assertTrue(files, "no evidence files found to verify")

        failures = []
        for path in files:
            if path.name in self.UNSIGNED_ARTIFACTS:
                continue
            ok, message = verify_evidence(path)
            if not ok:
                failures.append(f"{path.parent.name}/{path.name}: {message}")

        self.assertEqual(failures, [], "evidence failed verification")

    def test_unsigned_allowlist_has_no_stale_entries(self) -> None:
        """An allowlisted file that now verifies must leave the allowlist.

        Otherwise the exception outlives the reason for it and silently
        excuses a future regression on the same filename.
        """
        root = Path(__file__).resolve().parent.parent
        for name in self.UNSIGNED_ARTIFACTS:
            matches = list(root.glob(f"**/evidence/{name}"))
            for path in matches:
                ok, _ = verify_evidence(path)
                self.assertFalse(
                    ok, f"{name} verifies now -- remove it from UNSIGNED_ARTIFACTS")

    def test_preseeded_signature_field_cannot_poison_the_hash(self) -> None:
        """A producer that pre-seeds evidence_sha256 must still sign correctly.

        The COBOL adapter built its payload with ``"evidence_sha256": ""``
        already in the dict and hashed *that*, so the recorded hash covered a
        document that never existed on disk. canonical_hash() strips the field
        before hashing, which makes that mistake unrepresentable.
        """
        seeded = {"schema": "x/1", "results": {"a": 1}, "evidence_sha256": ""}
        clean = {"schema": "x/1", "results": {"a": 1}}
        self.assertEqual(canonical_hash(seeded), canonical_hash(clean))


if __name__ == "__main__":
    unittest.main()
