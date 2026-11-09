from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from config import settings


class PortalSettingsTests(unittest.TestCase):
    def test_environment_value_is_used_when_no_secret_exists(self):
        with (
            patch.object(settings, "st") as streamlit,
            patch.dict(os.environ, {"TOTALE_VERSAO": "4.2.0"}),
        ):
            streamlit.secrets.get.return_value = None

            self.assertEqual(settings.obter_versao_portal(), "4.2.0")

    def test_secret_has_precedence_over_environment(self):
        with (
            patch.object(settings, "st") as streamlit,
            patch.dict(os.environ, {"TOTALE_AMBIENTE": "Homologação"}),
        ):
            streamlit.secrets.get.return_value = "Produção"

            self.assertEqual(settings.obter_ambiente_portal(), "Produção")

    def test_empty_values_are_ignored(self):
        with (
            patch.object(settings, "st") as streamlit,
            patch.dict(os.environ, {"TOTALE_VERSAO": "  "}),
        ):
            streamlit.secrets.get.return_value = ""

            self.assertIsNone(settings.obter_versao_portal())

    def test_defaults_are_declared(self):
        self.assertEqual(settings.VERSAO_PORTAL_PADRAO, "3.7.0")
        self.assertEqual(settings.AMBIENTE_PORTAL_PADRAO, "Produção")


if __name__ == "__main__":
    unittest.main()
