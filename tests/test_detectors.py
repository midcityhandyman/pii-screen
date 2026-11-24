import unittest

from pii_screen.detectors import (
    Roster, detect, find_addresses, find_emails, find_phones,
)

ROSTER = Roster(["Alex Sample", "Robin Testcase", "Morgan Demo"])


def texts(findings):
    return [f.text for f in findings]


class EmailTests(unittest.TestCase):
    def test_finds_common_forms(self):
        text = "Write to alex.sample@example.com, or front-desk+jobs@mail.example.org."
        self.assertEqual(texts(find_emails(text)),
                         ["alex.sample@example.com", "front-desk+jobs@mail.example.org"])

    def test_ignores_bare_domains_and_handles(self):
        self.assertEqual(find_emails("see example.com/pricing or ping @frontdesk"), [])


class PhoneTests(unittest.TestCase):
    def test_finds_supported_formats(self):
        for phone in ["(555) 555-0142", "555-555-0142", "555.555.0142", "+1 555 555 0142",
                      "555 555 0142", "555-0142", "5555550142", "+15555550142",
                      "1-555-555-0142", "555-555-0142 ext. 7", "555-555-0142 x22"]:
            with self.subTest(phone=phone):
                self.assertEqual(texts(find_phones(f"call {phone} today")), [phone])

    def test_ignores_dates_money_and_long_ids(self):
        for text in ["Invoice 2026-11-03 total $1,250.00", "on 11/24/2026 at 10:30",
                     "tracking 123456789012", "ZIP 00000-1234", "ref #A-4471-22",
                     "version 10.4.2", "serial 00417-A"]:
            with self.subTest(text=text):
                self.assertEqual(find_phones(text), [])


class AddressTests(unittest.TestCase):
    def test_finds_street_addresses(self):
        for addr in ["123 Example Street", "42 Sample Ave, Apt 3B", "15 W 3rd St",
                     "700 N Mockingbird Lane, Faketown, ZZ 00000",
                     "1600 Test Blvd, Suite 200", "PO Box 12", "P.O. Box 440"]:
            with self.subTest(addr=addr):
                self.assertEqual(texts(find_addresses(f"Meet at {addr}. Thanks")), [addr])

    def test_does_not_swallow_sentence_period(self):
        self.assertEqual(texts(find_addresses("We are at 9 Placeholder Rd. See you.")),
                         ["9 Placeholder Rd"])

    def test_ignores_counts_and_measurements(self):
        self.assertEqual(find_addresses("Need 14 sheets of drywall and 3 easy ways to hang it"), [])


class RosterTests(unittest.TestCase):
    def test_full_name_any_case_and_reversed(self):
        text = "alex sample, ALEX SAMPLE and Sample, Alex"
        self.assertEqual(texts(ROSTER.find(text))[:3], ["alex sample", "ALEX SAMPLE", "Sample, Alex"])

    def test_single_part_needs_roster_capitalisation(self):
        self.assertEqual(texts(detect("Robin called. A robin sang.", ROSTER)), ["Robin"])

    def test_possessive(self):
        self.assertEqual(texts(detect("It is Alex's ladder", ROSTER)), ["Alex"])

    def test_full_names_only(self):
        strict = Roster(["Morgan Demo"], match_parts=False)
        self.assertEqual(texts(detect("Demo day. Morgan Demo confirmed.", strict)), ["Morgan Demo"])

    def test_no_roster_means_no_names(self):
        self.assertEqual(detect("Alex Sample called"), [])

    def test_from_file_skips_comments(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "roster.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# comment\n\nAlex Sample\n")
            self.assertEqual(Roster.from_file(path).names, ["Alex Sample"])


class OverlapTests(unittest.TestCase):
    def test_email_wins_over_name_inside_it(self):
        found = detect("mail Alex.Sample@example.com now", ROSTER)
        self.assertEqual([(f.kind, f.text) for f in found], [("EMAIL", "Alex.Sample@example.com")])

    def test_address_wins_over_surname_street(self):
        found = detect("go to 42 Sample Ave please", ROSTER)
        self.assertEqual([(f.kind, f.text) for f in found], [("ADDRESS", "42 Sample Ave")])

    def test_partial_overlap_is_merged_not_cut(self):
        # A "Last, First" name match that runs into an email used to win and
        # drop the email, leaving "@example.com" in the output.
        for text, span in [("Contact: Sample, alex@example.com today", "Sample, alex@example.com"),
                           ("Alex sample@example.com", "Alex sample@example.com")]:
            with self.subTest(text=text):
                found = detect(text, ROSTER)
                self.assertEqual([(f.kind, f.text) for f in found], [("EMAIL", span)])
                self.assertEqual(text[found[0].start:found[0].end], span)

    def test_findings_sorted_and_disjoint(self):
        found = detect("Alex Sample, 555-555-0142, alex@example.com, 123 Example Street", ROSTER)
        self.assertEqual([f.kind for f in found], ["NAME", "PHONE", "EMAIL", "ADDRESS"])
        for a, b in zip(found, found[1:]):
            self.assertLessEqual(a.end, b.start)


if __name__ == "__main__":
    unittest.main()
