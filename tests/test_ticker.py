from __future__ import annotations

import unittest
from unittest.mock import patch

from components.componentes import render_ticker


class TickerTests(unittest.TestCase):
    @patch("components.componentes.st.markdown")
    def test_ticker_escapes_dynamic_content_and_duplicates_track(self, markdown):
        render_ticker(
            [("<Ana & Cia>", "<script>alert(1)</script>")],
            label='Ticker "seguro"',
        )

        markup = markdown.call_args.args[0]
        self.assertIn("&lt;Ana &amp; Cia&gt;", markup)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", markup)
        self.assertNotIn("<script>", markup)
        self.assertIn('aria-label="Ticker &quot;seguro&quot;"', markup)
        self.assertEqual(markup.count("ticker-item"), 2)

    @patch("components.componentes.st.markdown")
    def test_ticker_with_no_items_does_not_render(self, markdown):
        render_ticker([])

        markdown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
