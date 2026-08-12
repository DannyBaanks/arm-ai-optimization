from __future__ import annotations

import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

from armopt.http_adapter import HttpAdapter, HttpAdapterConfig


class _OllamaFixtureHandler(BaseHTTPRequestHandler):
    received_options: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802 (stdlib method name)
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        self.received_options.append(request.get("options", {}))
        body = json.dumps({
            "response": request["prompt"],
            "prompt_eval_count": 3,
            "eval_count": 5,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # silence test output
        pass


class HttpAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        _OllamaFixtureHandler.received_options = []
        self.server = HTTPServer(("127.0.0.1", 0), _OllamaFixtureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        # addCleanup runs LIFO: register join() first so shutdown() (added
        # second) fires first and actually lets serve_forever() return.
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)
        port = self.server.server_address[1]
        self.adapter = HttpAdapter(HttpAdapterConfig(
            url=f"http://127.0.0.1:{port}", model="fixture-model", name="fixture",
        ))

    def test_infer_parses_ollama_style_response(self) -> None:
        response = self.adapter.infer("hello", max_tokens=8)
        self.assertEqual(response.text, "hello")
        self.assertEqual(response.input_tokens, 3)
        self.assertEqual(response.output_tokens, 5)

    def test_num_thread_is_omitted_by_default_and_sent_when_configured(self) -> None:
        self.adapter.infer("hello", max_tokens=8)
        self.assertNotIn("num_thread", _OllamaFixtureHandler.received_options[-1])

        port = self.server.server_address[1]
        threaded_adapter = HttpAdapter(HttpAdapterConfig(
            url=f"http://127.0.0.1:{port}", model="fixture-model", num_thread=2,
        ))
        threaded_adapter.infer("hello", max_tokens=8)
        self.assertEqual(_OllamaFixtureHandler.received_options[-1]["num_thread"], 2)

    def test_concurrent_calls_are_not_serialized_by_the_adapter(self) -> None:
        # Unlike JsonlAdapter's single-lock pipe, HttpAdapter holds no
        # adapter-side lock: N callers can be in-flight at once.
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(
                lambda i: self.adapter.infer(f"prompt {i}", max_tokens=8), range(8)
            ))
        self.assertEqual(len(responses), 8)
        for index, response in enumerate(responses):
            self.assertEqual(response.text, f"prompt {index}")


if __name__ == "__main__":
    unittest.main()
