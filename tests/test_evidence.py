from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from armopt.evidence import verify_evidence, write_evidence


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


if __name__ == "__main__":
    unittest.main()
