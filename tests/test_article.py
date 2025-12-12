import unittest

from newscli.article import DEFAULT_HEADERS, extract_readable_text


class TestArticleHeaders(unittest.TestCase):
    def test_accept_encoding_avoids_brotli(self) -> None:
        enc = (DEFAULT_HEADERS.get("Accept-Encoding") or "").lower()
        # Regression test: SG sites were returning brotli-encoded pages that
        # httpx couldn't decode without optional extras, producing garbled text.
        self.assertNotIn("br", enc)


class TestReadableText(unittest.TestCase):
    def test_plain_text_mirror_metadata_stripped(self) -> None:
        plain = (
            "Title: Example Mirror Title\n\n"
            "URL Source: http://example.com/article\n\n"
            "Published Time: Fri, 12 Dec 2025 07:32:20 GMT\n\n"
            "Markdown Content:\n"
            "First paragraph.\n\n"
            "Second paragraph.\n"
        )
        content = extract_readable_text(plain)
        self.assertEqual(content.title, "Example Mirror Title")
        self.assertIn("First paragraph.", content.text)
        self.assertIn("Second paragraph.", content.text)
        self.assertNotIn("URL Source:", content.text)
        self.assertNotIn("Published Time:", content.text)
        self.assertNotIn("Markdown Content:", content.text)

    def test_basic_html_extraction(self) -> None:
        html = (
            "<html><head><title>Fallback</title></head>"
            "<body><article><h1>Real Title</h1>"
            "<p>This is a long enough paragraph to be included in extraction.</p>"
            "<p>Another sufficiently long paragraph for testing purposes.</p>"
            "</article></body></html>"
        )
        content = extract_readable_text(html)
        self.assertEqual(content.title, "Real Title")
        self.assertIn("long enough paragraph", content.text)
        self.assertIn("Another sufficiently long paragraph", content.text)


if __name__ == "__main__":
    unittest.main()

