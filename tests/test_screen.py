import json
import os
import tempfile
import unittest

from pii_screen import BlockedError, Roster, Screener, Vault, guarded_call
from pii_screen.mock_model import MockModel

ROSTER = Roster(["Alex Sample", "Jordan Example"])
MESSAGE = ("Alex Sample (555-555-0142, alex.sample@example.com) wants a quote for "
           "123 Example Street. Alex Sample is home after 4.")
SECRETS = ["Alex", "Sample", "555-555-0142", "alex.sample@example.com", "123 Example Street"]


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.screener = Screener(ROSTER)

    def test_block_withholds_text(self):
        result = self.screener.screen(MESSAGE, "block")
        self.assertTrue(result.blocked)
        self.assertIsNone(result.text)
        self.assertEqual(result.counts(), {"NAME": 2, "PHONE": 1, "EMAIL": 1, "ADDRESS": 1})

    def test_block_passes_clean_text(self):
        result = self.screener.screen("The grout needs 24 hours to cure.", "block")
        self.assertFalse(result.blocked)
        self.assertEqual(result.text, "The grout needs 24 hours to cure.")

    def test_redact(self):
        result = self.screener.screen(MESSAGE, "redact")
        self.assertEqual(result.text, "[NAME] ([PHONE], [EMAIL]) wants a quote for [ADDRESS]. [NAME] is home after 4.")
        self.assertIsNone(result.vault)

    def test_tokenise_is_stable_and_reversible(self):
        result = self.screener.screen(MESSAGE, "tokenise")
        self.assertEqual(result.text.count("[[NAME_1]]"), 2)
        for secret in SECRETS:
            self.assertNotIn(secret, result.text)
        self.assertEqual(result.vault.restore(result.text), MESSAGE)

    def test_distinct_values_get_distinct_tokens(self):
        result = self.screener.screen("Alex Sample met Jordan Example", "tokenise")
        self.assertEqual(result.text, "[[NAME_1]] met [[NAME_2]]")

    def test_vault_reused_across_turns(self):
        vault = Vault()
        self.screener.screen("Call Alex Sample", "tokenise", vault)
        second = self.screener.screen("Jordan Example knows Alex Sample", "tokenise", vault)
        self.assertEqual(second.text, "[[NAME_2]] knows [[NAME_1]]")

    def test_literal_placeholder_in_input_is_not_reused(self):
        text = "The template says [[NAME_1]] but the customer is Alex Sample."
        result = self.screener.screen(text, "tokenise")
        self.assertIn("[[NAME_2]]", result.text)
        self.assertEqual(result.vault.restore(result.text), text)

    def test_unknown_mode_and_kind(self):
        with self.assertRaises(ValueError):
            self.screener.screen("x", "shred")
        with self.assertRaises(ValueError):
            Screener(kinds=["SSN"])

    def test_kinds_can_be_limited(self):
        result = Screener(ROSTER, kinds=["EMAIL"]).screen(MESSAGE, "redact")
        self.assertIn("555-555-0142", result.text)
        self.assertNotIn("alex.sample@example.com", result.text)


class VaultTests(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        result = Screener(ROSTER).screen(MESSAGE, "tokenise")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "vault.json")
            result.vault.save(path)
            loaded = Vault.load(path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), result.vault.to_dict())
        self.assertEqual(loaded.restore(result.text), MESSAGE)
        # a loaded vault keeps counting where it left off
        self.assertEqual(loaded.issue("NAME", "Jordan Example"), "[[NAME_2]]")
        self.assertEqual(loaded.issue("NAME", "Alex Sample"), "[[NAME_1]]")

    def test_restore_leaves_unknown_placeholders(self):
        self.assertEqual(Vault().restore("hello [[NAME_9]]"), "hello [[NAME_9]]")

    def test_from_dict_rejects_malformed_entries(self):
        for bad in [{"junk": "x"}, {"[[NAME_1]]": 5}, ["[[NAME_1]]"]]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    Vault.from_dict(bad)

    def test_overlapping_name_and_email_leave_no_tail(self):
        out = Screener(ROSTER).screen("Contact: Sample, alex@example.com", "redact").text
        self.assertEqual(out, "Contact: [EMAIL]")


class GuardedCallTests(unittest.TestCase):
    def test_model_never_sees_originals_and_reply_is_restored(self):
        model = MockModel()
        reply = guarded_call(Screener(ROSTER), MESSAGE, model.complete)
        for secret in SECRETS:
            self.assertNotIn(secret, model.seen[0])
        self.assertIn("Hello Alex Sample", reply)
        self.assertIn("123 Example Street", reply)
        self.assertNotIn("[[", reply)

    def test_block_mode_never_calls_model(self):
        model = MockModel()
        with self.assertRaises(BlockedError) as ctx:
            guarded_call(Screener(ROSTER), MESSAGE, model.complete, mode="block")
        self.assertEqual(model.seen, [])
        self.assertNotIn("Alex", str(ctx.exception))

    def test_redact_mode_reply_stays_redacted(self):
        model = MockModel()
        guarded_call(Screener(ROSTER), MESSAGE, model.complete, mode="redact")
        self.assertIn("[NAME]", model.seen[0])


if __name__ == "__main__":
    unittest.main()
