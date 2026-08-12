from __future__ import annotations

import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from armopt.http_adapter import HttpAdapter, HttpAdapterConfig


class _OllamaFixtureHandler(BaseHTTPRequestHandler):
    received_options: list[dict] = []
    response_delay_s: float = 0.0

    def do_POST(self) -> None:  # noqa: N802 (stdlib method name)
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        self.received_options.append(request.get("options", {}))
        time.sleep(self.response_delay_s)
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


class _LlamaServerFixtureHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        body = json.dumps({
            "content": request["prompt"],
            "tokens_evaluated": 4,
            "tokens_predicted": 6,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


def _start_server(handler: type[BaseHTTPRequestHandler], test: unittest.TestCase) -> int:
    # ThreadingHTTPServer, not the plain HTTPServer: the plain server
    # handles one request at a time regardless of how many clients connect
    # concurrently, which would make every concurrency test below
    # meaningless (it would "pass" by accident, serialized on the server).
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # addCleanup runs LIFO: register join() first so shutdown() (added
    # second) fires first and actually lets serve_forever() return.
    test.addCleanup(thread.join)
    test.addCleanup(server.shutdown)
    return server.server_address[1]


class HttpAdapterOllamaTests(unittest.TestCase):
    def setUp(self) -> None:
        _OllamaFixtureHandler.received_options = []
        _OllamaFixtureHandler.response_delay_s = 0.0
        port = _start_server(_OllamaFixtureHandler, self)
        self.url = f"http://127.0.0.1:{port}"
        self.adapter = HttpAdapter(HttpAdapterConfig(url=self.url, model="fixture-model", name="fixture"))

    def test_infer_parses_ollama_style_response(self) -> None:
        response = self.adapter.infer("hello", max_tokens=8)
        self.assertEqual(response.text, "hello")
        self.assertEqual(response.input_tokens, 3)
        self.assertEqual(response.output_tokens, 5)

    def test_num_thread_is_omitted_by_default_and_sent_when_configured(self) -> None:
        self.adapter.infer("hello", max_tokens=8)
        self.assertNotIn("num_thread", _OllamaFixtureHandler.received_options[-1])

        threaded_adapter = HttpAdapter(HttpAdapterConfig(url=self.url, model="fixture-model", num_thread=2))
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

    def test_concurrent_calls_actually_overlap_in_wall_time(self) -> None:
        # The proof, not just the absence-of-a-lock argument: 4 calls
        # against a server that each take ~0.3s should finish in ~0.3s
        # concurrently, not ~1.2s. (This is what isolated a real hackathon
        # bug: Ollama's own server turned out not to overlap requests even
        # though this adapter and this test both do.)
        _OllamaFixtureHandler.response_delay_s = 0.3
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: self.adapter.infer(f"p{i}", max_tokens=8), range(4)))
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.3 * 4 * 0.7, "4 concurrent calls took roughly as long as 4 sequential ones")


class HttpAdapterLlamaServerTests(unittest.TestCase):
    def setUp(self) -> None:
        port = _start_server(_LlamaServerFixtureHandler, self)
        self.adapter = HttpAdapter(HttpAdapterConfig(
            url=f"http://127.0.0.1:{port}", model="label-only", backend="llama_server",
        ))

    def test_infer_parses_llama_server_style_response(self) -> None:
        response = self.adapter.infer("hello", max_tokens=8)
        self.assertEqual(response.text, "hello")
        self.assertEqual(response.input_tokens, 4)
        self.assertEqual(response.output_tokens, 6)


if __name__ == "__main__":
    unittest.main()
