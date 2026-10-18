"""PDF invoices: text extraction (stdlib reader), its safety limits, and the upload path through the agent."""
import base64
import unittest
import zlib
from pathlib import Path

from agent.agent import Agent
from agent.model import OfflineModel
from agent.pdf import MAX_PDF_BYTES, PdfError, pdf_to_text

ROOT = Path(__file__).resolve().parent.parent
INVOICES = ROOT / "data" / "invoices"


def make_pdf(content, extra_objects=b"", font_dict=b"/F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
             flate=True):
    """A minimal one-page PDF whose page draws `content`."""
    stream = zlib.compress(content) if flate else content
    flt = b" /Filter /FlateDecode" if flate else b""
    return (b"%PDF-1.4\n1 0 obj << /Type /Page /Resources << /Font << " + font_dict + b" >> >> /Contents 2 0 R >> endobj\n"
            b"2 0 obj << /Length " + str(len(stream)).encode() + flt + b" >>\nstream\n" + stream +
            b"\nendstream\nendobj\n" + extra_objects + b"%%EOF")


class TestPdfText(unittest.TestCase):
    def test_sample_pdfs_read_like_their_json(self):
        for f in sorted(INVOICES.glob("INV-*.pdf")):
            with self.subTest(pdf=f.name):
                text = pdf_to_text(f.read_bytes())
                self.assertIn("SYNTHETIC TEST DOCUMENT", text)
                inv, _ = OfflineModel().extract(text)
                import json
                truth = json.loads(f.with_suffix(".json").read_text(encoding="utf-8"))
                self.assertEqual(inv["invoice_id"], truth["invoice_id"])
                self.assertEqual(inv["amount"], truth["amount"])
                self.assertEqual(inv.get("due_on"), truth.get("due_on"))
                self.assertEqual(inv["payee"]["name"], truth["payee"]["name"])
                self.assertEqual(inv["payee"]["bank"]["swift"], truth["payee"]["bank"]["swift"])

    def test_lines_rebuilt_by_position(self):
        content = (b"BT /F1 10 Tf 1 0 0 1 150 700 Tm (INV-9) Tj ET "
                   b"BT /F1 10 Tf 1 0 0 1 40 700 Tm (Invoice number:) Tj ET "
                   b"BT /F1 10 Tf 1 0 0 1 40 680 Tm [(TOTAL) -400 (DUE)] TJ 300 0 Td (USD 1,250.00) Tj ET")
        self.assertEqual(pdf_to_text(make_pdf(content)), "Invoice number:\tINV-9\nTOTAL DUE\tUSD 1,250.00")
        self.assertEqual(pdf_to_text(make_pdf(content, flate=False)).splitlines()[0], "Invoice number:\tINV-9")

    def test_escapes_and_hex_strings(self):
        content = rb"BT /F1 10 Tf 40 700 Td (Payee: Caf\351 \(Main\)) Tj 0 -20 Td <496E766F696365> Tj ET"
        self.assertEqual(pdf_to_text(make_pdf(content)), "Payee: Café (Main)\nInvoice")

    def test_embedded_font_through_tounicode_map(self):
        cmap = (b"begincmap 1 begincodespacerange <0000> <FFFF> endcodespacerange "
                b"2 beginbfchar <0001> <0041> <0002> <0042> endbfchar "
                b"1 beginbfrange <0010> <0012> <0058> endbfrange endcmap")
        extra = (b"3 0 obj << /Type /Font /Subtype /Type0 /ToUnicode 4 0 R >> endobj\n"
                 b"4 0 obj << /Length " + str(len(cmap)).encode() + b" >>\nstream\n" + cmap + b"\nendstream\nendobj\n")
        content = b"BT /C1 10 Tf 40 700 Td <000100020010001100120002> Tj ET"
        self.assertEqual(pdf_to_text(make_pdf(content, extra, font_dict=b"/C1 3 0 R")), "ABXYZB")

    def test_embedded_font_program_is_not_read_as_text(self):
        font = zlib.compress(b"\x00\x01BT garbage (not text) Tj ET\xff" * 3)
        extra = (b"3 0 obj << /Length " + str(len(font)).encode() + b" /Length1 999 /Filter /FlateDecode >>\nstream\n"
                 + font + b"\nendstream\nendobj\n")
        self.assertEqual(pdf_to_text(make_pdf(b"BT /F1 10 Tf 40 700 Td (Invoice No: X-1) Tj ET", extra)), "Invoice No: X-1")

    def test_unsafe_or_unreadable_pdfs_refused(self):
        bomb = make_pdf(b"BT (x) Tj ET " + b" " * (21 * 1024 * 1024))  # compresses tiny, unpacks past 20 MB
        cases = {"not a pdf": b"hello", "too big": b"%PDF-" + b"0" * MAX_PDF_BYTES,
                 "password": make_pdf(b"BT (x) Tj ET", b"5 0 obj << /Encrypt 6 0 R >> endobj\n"),
                 "zip bomb": bomb, "no text (a scan)": make_pdf(b"q 100 0 0 100 0 0 cm /Im1 Do Q")}
        for name, data in cases.items():
            with self.subTest(case=name), self.assertRaises(PdfError):
                pdf_to_text(data)


class TestPdfUpload(unittest.TestCase):
    def test_pdf_invoice_through_the_agent(self):
        a = Agent()
        s = a.new_session()
        a.consent(s["id"], True)
        a.upload_invoice(s["id"], pdf=base64.b64encode((INVOICES / "INV-04-missing-due-date.pdf").read_bytes()).decode())
        self.assertEqual(s["invoice"]["invoice_id"], "NBU-INV-2026-0203")
        self.assertEqual(a.pending_question(s)["field"], "due_on")  # asks, never guesses
        self.assertFalse(s["trust"]["verified"])  # a PDF carries no university signature, so it can never be paid
        self.assertTrue(any("<ACCOUNT_" in m["text"] for m in s["model_saw"]))  # account number masked for the model
        with self.assertRaises(ValueError):
            a.upload_invoice(s["id"], pdf="not base64!")


if __name__ == "__main__":
    unittest.main()
