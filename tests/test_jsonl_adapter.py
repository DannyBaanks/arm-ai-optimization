from __future__ import annotations

import json
import sys
import unittest

from armopt.jsonl_adapter import JsonlAdapter, JsonlAdapterConfig


SERVER = (
    "import sys,json; "
    "[print(json.dumps({'text': (x:=json.loads(l))['prompt'], "
    "'input_tokens': 1, 'output_tokens': 1}), flush=True) for l in sys.stdin]"
)


class JsonlAdapterTests(unittest.TestCase):
    def test_persistent_jsonl_adapter(self) -> None:
        with JsonlAdapter(JsonlAdapterConfig(
            command=[sys.executable, "-c", SERVER], name="fixture"
        )) as adapter:
            response = adapter.infer("hello", max_tokens=8)
        self.assertEqual(response.text, "hello")
        self.assertEqual(adapter.name, "fixture")


if __name__ == "__main__":
    unittest.main()
