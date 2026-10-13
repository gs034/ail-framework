"""Focused checks for the portable ailkit commands; no AIL server is needed."""
import argparse
import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "tools" / "ailkit.py"
spec = importlib.util.spec_from_file_location("ailkit", MODULE)
ailkit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ailkit)


class AilkitTests(unittest.TestCase):
    def test_file_hash_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case = base / "case"
            source = base / "sample.txt"
            source.write_text("sample evidence\n", encoding="utf-8")
            ailkit.init(argparse.Namespace(case=str(case), title="test"))
            ailkit.add_file(argparse.Namespace(case=str(case), file=str(source), source="test"))
            digest = ailkit.digest_file(source)
            self.assertEqual(ailkit.digest_file(case / "evidence" / digest), digest)
            self.assertEqual(len(ailkit.events(case)), 2)
            (case / "evidence" / digest).write_text("changed", encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                ailkit.verify(argparse.Namespace(case=str(case)))
            self.assertEqual(raised.exception.code, 2)

    def test_api_origin_rejects_remote_and_plain_http(self):
        for value in ("https://example.org:7000", "http://localhost:7000",
                      "https://localhost:7000/api", "https://user@localhost:7000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ailkit.ail_origin(value)
        self.assertEqual(ailkit.ail_origin("https://localhost:7000"),
                         "https://localhost:7000")


if __name__ == "__main__":
    unittest.main()
