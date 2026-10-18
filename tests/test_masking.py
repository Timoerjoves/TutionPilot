"""Name masking and the what-the-model-saw log: no person's name reaches the model."""
import unittest

from security import LeakError, Masker, ModelSawLog, find_identifiers, prepare_for_model

SYN_PAN = "ABCDE1234F"  # synthetic: valid shape, not a real PAN
INVOICE_TEXT = """NORTHBRIDGE UNIVERSITY (SYNTHETIC) - Student Accounts Office
Payee: Northbridge University (synthetic)
Invoice No: INV-SYN-0001
Student: Asha Student (synthetic)
Student ID: NBU-2026-1142
Bank account: XXXX-XXXX-4821
SWIFT: SYNTUS33"""


class TestNameMasking(unittest.TestCase):
    def test_student_name_masked_payee_kept(self):
        out = Masker().mask(INVOICE_TEXT)
        self.assertIn("Student: <NAME_1> (synthetic)", out)
        self.assertNotIn("Asha", out)
        self.assertIn("Payee: Northbridge University (synthetic)", out)
        self.assertIn("Student ID: NBU-2026-1142", out)
        self.assertIn("Student Accounts Office", out)

    def test_other_labels(self):
        out = Masker().mask("Father: Ravi Sample\nmother - Mira Sample\nRemitter: R Sample\nStudent's name: A Sample")
        self.assertEqual(find_identifiers(out), [])
        for raw in ("Ravi", "Mira", "R Sample", "A Sample"):
            self.assertNotIn(raw, out)

    def test_later_mention_same_token_and_round_trip(self):
        m = Masker()
        first = m.mask(INVOICE_TEXT)
        later = m.mask("Please pay the fee for ASHA STUDENT before the due date.")
        self.assertIn("<NAME_1>", later)
        self.assertNotIn("ASHA", later)
        self.assertIn("Asha Student", m.unmask(first))

    def test_remember_name(self):
        m = Masker()
        token = m.remember_name("  Ravi   Sample ")
        self.assertEqual(token, "<NAME_1>")
        self.assertEqual(m.mask("I am Ravi Sample, the father."), "I am <NAME_1>, the father.")
        self.assertIsNone(m.remember_name("   "))

    def test_whole_words_only(self):
        m = Masker()
        m.remember_name("Ash")
        self.assertEqual(m.mask("Ash paid by cash"), "<NAME_1> paid by cash")

    def test_name_with_other_spacing_or_line_break(self):
        m = Masker()
        m.mask("Student name: Riya Sample")
        out = m.mask("Pay for RIYA  SAMPLE, and also Riya\nSample.")
        self.assertNotIn("RIYA", out.upper().replace("<NAME_1>", ""))

    def test_name_ending_in_punctuation(self):
        m = Masker()
        m.mask("Father: Anil K.")
        self.assertEqual(m.mask("Anil K. will pay"), "<NAME_1> will pay")

    def test_ids_and_university_are_not_names(self):
        for line in ("Student-ID: NBU-2026-1142", "Name: Northbridge University (synthetic)",
                     "Payee name: Northbridge University"):
            self.assertEqual(Masker().mask(line), line)

    def test_one_word_value_is_not_masked_everywhere(self):
        m = Masker()
        self.assertEqual(m.mask("Remitter: self"), "Remitter: <NAME_1>")
        self.assertEqual(m.mask("I will pay it myself, from self funds."), "I will pay it myself, from self funds.")
        self.assertEqual(Masker().mask("Student: Fee\nThe provider fee"), "Student: <NAME_1>\nThe provider fee")

    def test_unmask_obj(self):
        m = Masker()
        masked = m.mask_obj({"student": {"name": "Student: Asha Student"}, "n": 3})
        self.assertEqual(m.unmask_obj(masked), {"student": {"name": "Student: Asha Student"}, "n": 3})

    def test_other_kinds_unchanged(self):
        out = Masker().mask(f"Student: Asha Student\nPAN {SYN_PAN}")
        self.assertIn("<NAME_1>", out)
        self.assertIn("<PAN_1>", out)


class TestModelSawLog(unittest.TestCase):
    def test_log_refuses_a_raw_name_without_echoing_it(self):
        with self.assertRaises(LeakError) as e:
            ModelSawLog().record("x", "Student: Asha Student")
        self.assertIn("NAME", str(e.exception))
        self.assertNotIn("Asha", str(e.exception))

    def test_masked_name_is_accepted(self):
        ModelSawLog().record("x", "Student: <NAME_1> (synthetic)")

    def test_prepare_for_model_logs_no_names(self):
        log = ModelSawLog()
        sent = prepare_for_model(Masker(), log, "extract_invoice", INVOICE_TEXT)
        self.assertEqual(log.entries[0]["text"], sent)
        self.assertNotIn("Asha", sent)
        self.assertEqual(find_identifiers(sent), [])


class TestAgentPath(unittest.TestCase):
    """End to end through the agent: what the model saw has no names, the family still sees them."""

    def setUp(self):
        import tempfile
        from agent.agent import Agent
        self.a = Agent(evidence_dir=tempfile.mkdtemp())
        self.sid = self.a.new_session("parent")["id"]
        self.a.consent(self.sid, True)

    def test_remitter_name_masked_in_later_chat(self):
        self.a.upload_invoice(self.sid, sample="valid_us")
        self.a.answer(self.sid, "remitter_name", "Ravi Parent")
        s = self.a.get(self.sid)
        while self.a.pending_question(s):  # answer the rest so chat goes to the model, not to a question
            q = self.a.pending_question(s)
            self.a.answer(self.sid, q["field"], {"pan": SYN_PAN, "relationship": "Father", "funding": "Own money",
                                                 "prior_inr": "0", "prior_other": "No"}.get(q["field"], "0"))
        self.a.chat(self.sid, "Ravi Parent will pay from savings, which route is best?")
        saw = self.a.get(self.sid)["model_saw"]
        chat = [e["text"] for e in saw if e["purpose"] == "chat"]
        self.assertEqual(len(chat), 1)
        self.assertTrue(chat[0].startswith("<NAME_2> will pay"), chat[0])
        self.assertNotIn("Ravi", " ".join(e["text"] for e in saw))

    def test_unverified_invoice_keeps_real_student_name_for_the_family(self):
        self.a.upload_invoice(self.sid, sample="unsigned")
        s = self.a.get(self.sid)
        self.assertNotIn("<NAME_", s["invoice"]["student"]["name"])
        self.assertNotIn("Asha", " ".join(e["text"] for e in s["model_saw"]))


if __name__ == "__main__":
    unittest.main()
