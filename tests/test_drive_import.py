import unittest
from unittest.mock import patch

import pandas as pd

import drive_import
import production


class FakeResponse:
    def __init__(self, *, data=None, content=b""):
        self.data = data
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        return self.responses.pop(0)


class DriveImportTests(unittest.TestCase):
    def test_list_folder_files_follows_page_tokens(self):
        session = FakeSession(
            [
                FakeResponse(
                    data={
                        "files": [{"id": "one", "name": "jan.xlsx"}],
                        "nextPageToken": "next-page",
                    }
                ),
                FakeResponse(data={"files": [{"id": "two", "name": "fev.csv"}]}),
            ]
        )

        files = drive_import.list_folder_files(session, "folder-id")

        self.assertEqual([file["id"] for file in files], ["one", "two"])
        self.assertEqual(session.calls[1][1]["pageToken"], "next-page")

    def test_import_drive_folder_parses_csv_points(self):
        session = FakeSession(
            [
                FakeResponse(
                    data={
                        "files": [
                            {
                                "id": "file-id",
                                "name": "producao.csv",
                                "mimeType": "text/csv",
                            }
                        ]
                    }
                ),
                FakeResponse(
                    content=(
                        "Técnico;Data;Pontos\nAna;11/2026;125,5\n"
                        "Ana;11/2026;10\n"
                    ).encode()
                ),
            ]
        )
        with patch("drive_import.create_drive_session", return_value=session):
            records, issues, successful_files = drive_import.import_drive_folder(
                {}, "folder-id"
            )

        self.assertEqual(issues, [])
        self.assertEqual(successful_files, 1)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["points"], 125.5)
        self.assertIn("file-id", records[0]["source_file"])
        total = production.summarize(
            pd.DataFrame(records), ["technician", "reference_date"]
        ).iloc[0]
        self.assertEqual(total["points_total"], 135.5)

    def test_unsupported_file_is_not_downloaded(self):
        session = FakeSession([])

        result = drive_import.download_file(
            session,
            {"id": "doc-id", "name": "readme.pdf", "mimeType": "application/pdf"},
        )

        self.assertIsNone(result)
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
