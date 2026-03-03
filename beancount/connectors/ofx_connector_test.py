"""Tests for the OFX connector."""

import datetime
import os
import tempfile
import textwrap
import unittest

from beancount.connectors.ofx_connector import OFXConnector
from beancount.core.number import D


class TestOFXConnector(unittest.TestCase):
    def test_identify_by_extension(self):
        conn = OFXConnector()
        self.assertTrue(conn.identify("test.ofx"))
        self.assertTrue(conn.identify("test.qfx"))
        self.assertFalse(conn.identify("test.csv"))

    def test_identify_by_content(self):
        content = "OFXHEADER:100\n<OFX>\n</OFX>"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write(content)
            tmpfile = f.name
        try:
            conn = OFXConnector()
            self.assertTrue(conn.identify(tmpfile))
        finally:
            os.unlink(tmpfile)

    def test_extract_xml_ofx(self):
        content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <OFX>
              <BANKMSGSRSV1>
                <STMTTRNRS>
                  <STMTRS>
                    <BANKTRANLIST>
                      <STMTTRN>
                        <TRNTYPE>DEBIT</TRNTYPE>
                        <DTPOSTED>20240115120000</DTPOSTED>
                        <TRNAMT>-45.00</TRNAMT>
                        <FITID>20240115001</FITID>
                        <NAME>GROCERY STORE</NAME>
                        <MEMO>Purchase at Grocery Store</MEMO>
                      </STMTTRN>
                      <STMTTRN>
                        <TRNTYPE>CREDIT</TRNTYPE>
                        <DTPOSTED>20240116120000</DTPOSTED>
                        <TRNAMT>5000.00</TRNAMT>
                        <FITID>20240116001</FITID>
                        <NAME>EMPLOYER INC</NAME>
                        <MEMO>Salary deposit</MEMO>
                      </STMTTRN>
                    </BANKTRANLIST>
                  </STMTRS>
                </STMTTRNRS>
              </BANKMSGSRSV1>
            </OFX>
        """)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ofx", delete=False
        ) as f:
            f.write(content)
            tmpfile = f.name

        try:
            conn = OFXConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 2)

            # Check first transaction (debit).
            self.assertEqual(entries[0].date, datetime.date(2024, 1, 15))
            self.assertEqual(entries[0].payee, "GROCERY STORE")
            self.assertEqual(entries[0].narration, "Purchase at Grocery Store")
            self.assertEqual(entries[0].postings[0].units.number, D("-45.00"))
            self.assertEqual(entries[0].meta.get("ofx_fitid"), "20240115001")

            # Check second transaction (credit).
            self.assertEqual(entries[1].date, datetime.date(2024, 1, 16))
            self.assertEqual(entries[1].postings[0].units.number, D("5000.00"))
        finally:
            os.unlink(tmpfile)

    def test_extract_empty_ofx(self):
        content = '<?xml version="1.0"?><OFX></OFX>'
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ofx", delete=False
        ) as f:
            f.write(content)
            tmpfile = f.name

        try:
            conn = OFXConnector()
            entries = conn.extract(tmpfile)
            self.assertEqual(entries, [])
        finally:
            os.unlink(tmpfile)

    def test_extract_nonexistent_file(self):
        conn = OFXConnector()
        entries = conn.extract("/nonexistent/file.ofx")
        self.assertEqual(entries, [])

    def test_sgml_to_xml(self):
        conn = OFXConnector()
        sgml = "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20240115<TRNAMT>-100.00"
        xml = conn._sgml_to_xml(sgml)
        # Should have closing tags.
        self.assertIn("</TRNTYPE>", xml)
        self.assertIn("</DTPOSTED>", xml)
        self.assertIn("</TRNAMT>", xml)


class TestOFXConnectorConfig(unittest.TestCase):
    def test_apply_config(self):
        conn = OFXConnector()
        config = {
            "default_account": "Assets:Bank",
            "default_currency": "EUR",
            "account_map": {"1234": "Assets:Savings"},
        }
        conn._apply_config(config)
        self.assertEqual(conn.default_account, "Assets:Bank")
        self.assertEqual(conn.default_currency, "EUR")
        self.assertEqual(conn.account_map, {"1234": "Assets:Savings"})


if __name__ == "__main__":
    unittest.main()
