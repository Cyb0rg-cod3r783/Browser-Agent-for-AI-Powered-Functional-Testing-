"""
Test Data Generator
Produces typed random values for every category a tester would care about:
valid, invalid, boundary, empty, wrong-type, injection, unicode, etc.
"""
import random
import string
import uuid
from typing import Any

# ── Character sets ────────────────────────────────────────────────────────────
SPECIAL_CHARS  = '!@#$%^&*()_+-=[]{}|;:\'",.<>?/\\'
SQL_INJECTIONS = [
    "' OR '1'='1",  "'; DROP TABLE users; --",  "' UNION SELECT * FROM users --",
    "1; SELECT * FROM information_schema.tables",  "admin'--",  "' OR 1=1--",
]
XSS_PAYLOADS = [
    "<script>alert('XSS')</script>",  "<img src=x onerror=alert(1)>",
    "javascript:alert(1)",  "<svg onload=alert(1)>",
    "';alert(String.fromCharCode(88,83,83))//",
]
UNICODE_STRINGS = [
    "日本語テスト",  "Ünïcödé tëst",  "中文测试",  "العربية",
    "emoji 🎉🚀💥",  "null\x00byte",  "line\nbreak",  "tab\there",
    "\u202e reversed",  "𝕳𝖊𝖑𝖑𝖔",
]
LONG_STRINGS = [
    "A" * 256, "B" * 1000, "C" * 5001, " " * 200, "\t" * 100,
]


class TestDataService:
    """
    Centralised factory for test values.
    Every method returns a list of (value, label) tuples so the caller
    knows what category each value belongs to.
    """

    # ── Email ─────────────────────────────────────────────────────────────────
    def email_values(self):
        return [
            ("user@example.com",          "valid_standard"),
            ("user+tag@sub.domain.org",   "valid_tagged"),
            ("test.email@company.co.uk",  "valid_subdomain"),
            ("",                           "empty"),
            ("notanemail",                 "invalid_no_at"),
            ("@nodomain.com",              "invalid_no_local"),
            ("user@",                      "invalid_no_domain"),
            ("user @example.com",          "invalid_space"),
            ("user@exam ple.com",          "invalid_space_domain"),
            ("a" * 250 + "@test.com",      "boundary_too_long"),
            (SPECIAL_CHARS[:10] + "@t.c",  "invalid_special_chars"),
            ("user@.com",                  "invalid_dot_start"),
            ("<script>@xss.com",           "xss_attempt"),
            ("' OR 1=1--@test.com",        "sql_injection"),
            ("user@" + "a" * 64 + ".com", "boundary_long_domain"),
            ("1234567890@numbers.com",     "valid_numeric_local"),
            ("  spaces@test.com  ",        "whitespace_padded"),
        ]

    # ── Password ──────────────────────────────────────────────────────────────
    def password_values(self):
        return [
            ("Correct$Horse#Battery1",    "valid_strong"),
            ("short1A!",                   "valid_min_length"),
            ("P@ssw0rd",                   "valid_common_pattern"),
            ("",                           "empty"),
            ("a",                          "boundary_too_short"),
            ("A" * 129,                    "boundary_too_long"),
            ("alllowercase1!",             "invalid_no_uppercase"),
            ("ALLUPPERCASE1!",             "invalid_no_lowercase"),
            ("NoNumbers!",                 "invalid_no_number"),
            ("NoSpecial1",                 "invalid_no_special"),
            ("password",                   "invalid_common"),
            ("123456",                     "invalid_all_numbers"),
            (SQL_INJECTIONS[0],            "sql_injection"),
            (XSS_PAYLOADS[0],             "xss_payload"),
            (" " * 10,                     "invalid_only_spaces"),
            ("Pass\x00word1!",             "invalid_null_byte"),
            ("p" + "a" * 72 + "ss1!",     "boundary_long_valid"),
            ("日本語パスワード1!",          "unicode_password"),
        ]

    # ── Name / Text ───────────────────────────────────────────────────────────
    def name_values(self):
        return [
            ("John Doe",                   "valid_full_name"),
            ("Alice",                      "valid_single_name"),
            ("Mary-Jane O'Brien",          "valid_hyphen_apostrophe"),
            ("José García",               "valid_accented"),
            ("",                           "empty"),
            (" ",                          "whitespace_only"),
            ("A" * 256,                    "boundary_too_long"),
            ("A",                          "boundary_single_char"),
            ("123 Numbers",                "invalid_starts_with_number"),
            ("<script>XSS</script>",       "xss_payload"),
            ("' OR 1=1--",                 "sql_injection"),
            ("日本語 名前",                 "unicode_japanese"),
            ("Name\nWith\nNewlines",        "invalid_newlines"),
            ("Name\tWith\tTabs",           "invalid_tabs"),
            (SPECIAL_CHARS,               "all_special_chars"),
            ("🎉 Emoji Name 🚀",           "emoji_name"),
        ]

    # ── Phone number ──────────────────────────────────────────────────────────
    def phone_values(self):
        return [
            ("+1 (555) 123-4567",          "valid_us_formatted"),
            ("5551234567",                  "valid_us_plain"),
            ("+44 20 7946 0958",            "valid_uk"),
            ("+91 98765 43210",             "valid_india"),
            ("",                            "empty"),
            ("abc-defg-hijk",               "invalid_letters"),
            ("123",                         "boundary_too_short"),
            ("1" * 16,                      "boundary_too_long"),
            ("+0000000000",                 "invalid_all_zeros"),
            ("++1234567890",                "invalid_double_plus"),
            ("(555) 123-456789012",         "invalid_too_many_digits"),
            (SQL_INJECTIONS[0],            "sql_injection"),
            ("<script>alert(1)</script>",   "xss_payload"),
            ("000-000-0000",                "boundary_all_zeros_formatted"),
            ("999-999-9999",                "boundary_all_nines"),
        ]

    # ── Number / Age / Quantity ───────────────────────────────────────────────
    def number_values(self):
        return [
            ("1",                          "boundary_min"),
            ("0",                          "boundary_zero"),
            ("-1",                         "boundary_negative"),
            ("100",                        "valid_typical"),
            ("999999",                     "boundary_large"),
            ("2147483647",                 "boundary_int_max"),
            ("2147483648",                 "boundary_int_overflow"),
            ("-2147483649",                "boundary_int_underflow"),
            ("3.14",                       "valid_float"),
            ("1.123456789012345678",        "boundary_float_precision"),
            ("",                           "empty"),
            ("abc",                        "invalid_letters"),
            ("12 34",                      "invalid_space"),
            ("1e10",                       "valid_scientific"),
            ("0x1F",                       "invalid_hex"),
            ("NaN",                        "invalid_nan"),
            ("Infinity",                   "invalid_infinity"),
            (SQL_INJECTIONS[0],           "sql_injection"),
        ]

    # ── URL / Link ────────────────────────────────────────────────────────────
    def url_values(self):
        return [
            ("https://example.com",        "valid_https"),
            ("http://example.com",         "valid_http"),
            ("https://sub.domain.co.uk/path?q=1#anchor", "valid_complex"),
            ("",                           "empty"),
            ("not-a-url",                  "invalid_no_protocol"),
            ("ftp://invalid.com",          "invalid_ftp_protocol"),
            ("javascript:alert(1)",        "xss_javascript_protocol"),
            ("https://",                   "invalid_no_host"),
            ("https://" + "a" * 2000,      "boundary_too_long"),
            ("http://localhost:8080",       "valid_localhost"),
            ("<script>alert(1)</script>",   "xss_payload"),
            ("' OR 1=1--",                 "sql_injection"),
        ]

    # ── Date ──────────────────────────────────────────────────────────────────
    def date_values(self):
        return [
            ("2000-01-01",                 "valid_standard"),
            ("1990-12-31",                 "valid_past"),
            ("2099-12-31",                 "valid_future"),
            ("",                           "empty"),
            ("1899-12-31",                 "boundary_before_1900"),
            ("2000-02-29",                 "valid_leap_day"),
            ("1900-02-29",                 "invalid_not_leap_year"),
            ("2000-13-01",                 "invalid_month_13"),
            ("2000-00-01",                 "invalid_month_0"),
            ("2000-01-32",                 "invalid_day_32"),
            ("2000-01-00",                 "invalid_day_0"),
            ("not-a-date",                 "invalid_string"),
            ("12/31/2000",                 "valid_us_format"),
            ("31-12-2000",                 "valid_eu_format"),
            (SQL_INJECTIONS[0],           "sql_injection"),
            ("9999-99-99",                 "boundary_max"),
        ]

    # ── Generic text / search ─────────────────────────────────────────────────
    def text_values(self):
        return [
            ("Hello World",                "valid_simple"),
            ("",                           "empty"),
            (" ",                          "whitespace_only"),
            ("A" * 256,                    "boundary_256_chars"),
            ("A" * 5001,                   "boundary_very_long"),
            (SQL_INJECTIONS[0],           "sql_injection"),
            (SQL_INJECTIONS[1],           "sql_drop_table"),
            (XSS_PAYLOADS[0],            "xss_script_tag"),
            (XSS_PAYLOADS[1],            "xss_img_tag"),
            (UNICODE_STRINGS[0],          "unicode_japanese"),
            (UNICODE_STRINGS[4],          "unicode_emoji"),
            (UNICODE_STRINGS[5],          "null_byte"),
            ("\n" * 10,                   "newlines_only"),
            ("Hello\x00World",            "embedded_null_byte"),
            (SPECIAL_CHARS,              "all_special_chars"),
            ("<b>Bold</b><i>Italic</i>",  "html_tags"),
            ("../../../etc/passwd",        "path_traversal"),
            ("%00%0a%0d%0d%0a",          "url_encoded_chars"),
        ]

    # ── Credit card (test numbers only) ──────────────────────────────────────
    def credit_card_values(self):
        return [
            ("4111111111111111",           "valid_visa_test"),
            ("5500005555555559",           "valid_mastercard_test"),
            ("378282246310005",            "valid_amex_test"),
            ("6011111111111117",           "valid_discover_test"),
            ("",                           "empty"),
            ("1234567890123456",           "invalid_luhn_fail"),
            ("4111-1111-1111-1111",        "valid_formatted"),
            ("4111 1111 1111 1111",        "valid_spaces"),
            ("411111111111111",            "boundary_too_short"),
            ("41111111111111111",          "boundary_too_long"),
            ("abcdefghijklmnop",           "invalid_letters"),
            (SQL_INJECTIONS[0],           "sql_injection"),
        ]

    def get_values_for_field_type(self, field_type: str) -> list:
        """Auto-detect which value set to use based on semantic field type."""
        t = field_type.lower()
        if any(k in t for k in ["email"]):
            return self.email_values()
        if any(k in t for k in ["password", "passwd", "secret"]):
            return self.password_values()
        if any(k in t for k in ["phone", "mobile", "tel", "cell"]):
            return self.phone_values()
        if any(k in t for k in ["name", "first", "last", "full"]):
            return self.name_values()
        if any(k in t for k in ["age", "count", "qty", "quantity", "amount", "price", "number", "num", "year"]):
            return self.number_values()
        if any(k in t for k in ["url", "website", "link", "href"]):
            return self.url_values()
        if any(k in t for k in ["date", "birth", "dob", "expiry"]):
            return self.date_values()
        if any(k in t for k in ["card", "credit", "cc_", "cvv", "cvc"]):
            return self.credit_card_values()
        return self.text_values()

    def random_valid_value(self, field_type: str) -> str:
        """Return one valid random value for a field type."""
        vals = [v for v, label in self.get_values_for_field_type(field_type)
                if "valid" in label]
        return random.choice(vals)[0] if vals else "test_value"


test_data_service = TestDataService()
