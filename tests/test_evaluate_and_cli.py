import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from pii_screen import Roster, Screener
from pii_screen.cli import main
from pii_screen.evaluate import format_report, load_corpus, score

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus" / "corpus.jsonl"
ROSTER = ROOT / "corpus" / "roster.txt"


def run_cli(argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    import sys
    old = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
    finally:
        sys.stdin = old
    return code, out.getvalue(), err.getvalue()


class ScoringTests(unittest.TestCase):
    def test_counts_on_a_tiny_corpus(self):
        examples = [
            # exact hit on the email, partial hit on the name, one false positive phone
            {"id": "t1", "text": "A. Sample, a@example.com, part 400-2210",
             "spans": [{"start": 0, "end": 9, "type": "NAME"}, {"start": 11, "end": 24, "type": "EMAIL"}]},
            # one miss
            {"id": "t2", "text": "ring 555 0142", "spans": [{"start": 5, "end": 13, "type": "PHONE"}]},
        ]
        report = score(Screener(Roster(["Alex Sample"])), examples)
        email, name, phone = report.by_kind["EMAIL"], report.by_kind["NAME"], report.by_kind["PHONE"]
        self.assertEqual((email.tp, email.fp, email.fn), (1, 0, 0))
        self.assertEqual((name.tp, name.fp, name.fn), (0, 1, 1))
        self.assertEqual((name.relaxed_precision, name.relaxed_recall), (1.0, 1.0))
        self.assertEqual((phone.tp, phone.fp, phone.fn), (0, 1, 1))
        self.assertEqual(phone.relaxed_recall, 0.0)
        overall = report.overall
        self.assertAlmostEqual(overall.precision, 1 / 3)
        self.assertAlmostEqual(overall.recall, 1 / 3)
        self.assertEqual(len(report.errors), 4)
        self.assertIn("ALL", format_report(report, show_errors=True))


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.examples = load_corpus(CORPUS)

    def test_offsets_match_text(self):
        self.assertGreaterEqual(len(self.examples), 100)
        for ex in self.examples:
            for span in ex["spans"]:
                self.assertEqual(ex["text"][span["start"]:span["end"]], span["text"], ex["id"])

    def test_shipped_files_match_the_builder(self):
        spec = importlib.util.spec_from_file_location("build_corpus", ROOT / "corpus" / "build_corpus.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        self.assertEqual(builder.render(builder.build()), CORPUS.read_text(encoding="utf-8"))
        self.assertEqual(Roster.from_file(ROSTER).names, builder.ROSTER)

    def test_only_synthetic_contact_details(self):
        for ex in self.examples:
            for span in ex["spans"]:
                if span["type"] == "EMAIL" and "@" in span["text"]:
                    self.assertRegex(span["text"].lower(), r"@(mail\.)?example\.(com|org|net)$")

    def test_quality_floor(self):
        # Regression guard, set a little under the measured numbers in the README.
        overall = score(Screener(Roster.from_file(ROSTER)), self.examples).overall
        self.assertGreaterEqual(overall.precision, 0.92)
        self.assertGreaterEqual(overall.recall, 0.91)


class CliTests(unittest.TestCase):
    def test_tokenise_then_restore(self):
        text = "Alex Sample, 555-555-0142"
        with tempfile.TemporaryDirectory() as d:
            vault = os.path.join(d, "vault.json")
            code, out, err = run_cli(["screen", "--roster", str(ROSTER), "--vault", vault], stdin=text)
            self.assertEqual((code, out), (0, "[[NAME_1]], [[PHONE_1]]"))
            self.assertNotIn("Alex", err)
            code, restored, _ = run_cli(["restore", "--vault", vault], stdin=out)
            self.assertEqual((code, restored), (0, text))

    def test_block_exits_2_and_prints_nothing(self):
        code, out, err = run_cli(["screen", "--mode", "block"], stdin="mail a@example.com")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("BLOCKED", err)
        self.assertNotIn("a@example.com", err)

    def test_redact_json_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "msg.txt")
            Path(path).write_text("mail a@example.com", encoding="utf-8")
            code, out, _ = run_cli(["screen", path, "--mode", "redact", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"mode": "redact", "text": "mail [EMAIL]", "counts": {"EMAIL": 1}})

    def test_env_sets_default_mode(self):
        os.environ["PII_SCREEN_MODE"] = "redact"
        try:
            code, out, _ = run_cli(["screen"], stdin="call 555-0142")
        finally:
            del os.environ["PII_SCREEN_MODE"]
        self.assertEqual((code, out), (0, "call [PHONE]"))

    def test_eval_prints_report(self):
        code, out, _ = run_cli(["eval"])
        self.assertEqual(code, 0)
        self.assertIn("Exact span match", out)

    def test_missing_file_is_an_error(self):
        code, _, err = run_cli(["screen", "no-such-file.txt"])
        self.assertEqual(code, 1)
        self.assertIn("error", err)


if __name__ == "__main__":
    unittest.main()
