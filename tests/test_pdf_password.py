import unittest
from unittest.mock import patch

from pdfminer.pdfdocument import PDFPasswordIncorrect
from bankflow_v2.pdf_password import pdf_requires_password


class PdfPasswordTests(unittest.TestCase):
    def test_permission_encryption_with_empty_password_does_not_prompt(self):
        with patch("bankflow_v2.pdf_password._touch_pdf", return_value=True):
            self.assertFalse(pdf_requires_password("sample.pdf"))

    def test_open_password_failure_requires_password(self):
        with patch("bankflow_v2.pdf_password._touch_pdf", side_effect=PDFPasswordIncorrect()):
            self.assertTrue(pdf_requires_password("sample.pdf"))

    def test_unrelated_error_is_not_a_password_requirement(self):
        with patch("bankflow_v2.pdf_password._touch_pdf", side_effect=FileNotFoundError()):
            with self.assertRaises(FileNotFoundError):
                pdf_requires_password("sample.pdf")
