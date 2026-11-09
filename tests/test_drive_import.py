import unittest
from threading import Barrier
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

    def test_snapshot_tracks_files_and_successfully_refreshed_ids(self):
        session = FakeSession(
            [
                FakeResponse(
                    data={
                        "files": [
                            {
                                "id": "file-id",
                                "name": "producao.csv",
                                "mimeType": "text/csv",
                                "modifiedTime": "2026-11-06T12:00:00Z",
                            }
                        ]
                    }
                ),
                FakeResponse(content=b"Tecnico;Data;Pontos\nAna;11/2026;10\n"),
            ]
        )
        with patch("drive_import.create_drive_session", return_value=session):
            result = drive_import.import_drive_folder_snapshot({}, "folder-id")

        self.assertEqual(result.file_ids, {"file-id"})
        self.assertEqual(result.refreshed_file_ids, {"file-id"})
        self.assertEqual(result.successful_files, 1)
        self.assertIn("file-id", result.file_fingerprints)

    def test_snapshot_skips_unchanged_files(self):
        drive_file = {
            "id": "file-id",
            "name": "producao.csv",
            "mimeType": "text/csv",
            "modifiedTime": "2026-11-06T12:00:00Z",
        }
        session = FakeSession([FakeResponse(data={"files": [drive_file]})])
        fingerprint = drive_import._file_fingerprint(drive_file)
        self.assertIsNotNone(fingerprint)

        with (
            patch("drive_import.create_drive_session", return_value=session),
            patch("drive_import.download_file") as download,
        ):
            result = drive_import.import_drive_folder_snapshot(
                {},
                "folder-id",
                known_file_fingerprints={"file-id": fingerprint},
            )

        download.assert_not_called()
        self.assertEqual(result.file_ids, {"file-id"})
        self.assertEqual(result.refreshed_file_ids, set())
        self.assertEqual(result.successful_files, 0)

    def test_snapshot_reimports_files_after_contract_parser_change(self):
        drive_file = {
            "id": "file-id",
            "name": "producao.csv",
            "mimeType": "text/csv",
            "modifiedTime": "2026-11-06T12:00:00Z",
        }
        session = FakeSession([FakeResponse(data={"files": [drive_file]})])
        legacy_fingerprint = "producao.csv|text/csv|2026-11-06T12:00:00Z||"

        with (
            patch("drive_import.create_drive_session", return_value=session),
            patch(
                "drive_import.download_file",
                return_value=(
                    "producao [file-id].csv",
                    b"Tecnico;Data;Pontos;Contrato\nAna;11/2026;10;001\n",
                ),
            ) as download,
        ):
            result = drive_import.import_drive_folder_snapshot(
                {},
                "folder-id",
                known_file_fingerprints={"file-id": legacy_fingerprint},
            )

        download.assert_called_once()
        self.assertEqual(result.refreshed_file_ids, {"file-id"})
        self.assertEqual(result.records[0]["contract"], "001")

    def test_snapshot_downloads_files_in_parallel(self):
        files = [
            {"id": "one", "name": "one.csv", "mimeType": "text/csv"},
            {"id": "two", "name": "two.csv", "mimeType": "text/csv"},
        ]
        session = FakeSession([FakeResponse(data={"files": files})])
        barrier = Barrier(2)

        def download_file(_session, drive_file):
            barrier.wait(timeout=5)
            content = f"Tecnico;Data;Pontos\n{drive_file['id']};11/2026;10\n".encode()
            return f"{drive_file['name']} [{drive_file['id']}].csv", content

        with (
            patch("drive_import.create_drive_session", return_value=session),
            patch("drive_import.download_file", side_effect=download_file),
        ):
            result = drive_import.import_drive_folder_snapshot({}, "folder-id")

        self.assertEqual(result.successful_files, 2)
        self.assertEqual(result.refreshed_file_ids, {"one", "two"})
        self.assertEqual(len(result.records), 2)

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
