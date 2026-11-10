import unittest
from datetime import date
from threading import Barrier
from unittest.mock import patch

import pandas as pd
import requests

import drive_import
import production


class FakeResponse:
    def __init__(self, *, data: dict | None = None, content: bytes = b"") -> None:
        self.data = data
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict | None:
        return self.data


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict | None, int | None]] = []

    def get(
        self, url: str, *, params: dict | None = None, timeout: int | None = None
    ) -> FakeResponse:
        self.calls.append((url, params, timeout))
        return self.responses.pop(0)


class DriveImportTests(unittest.TestCase):
    def test_list_folder_files_follows_page_tokens(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    data={
                        "files": [
                            {
                                "id": "one",
                                "name": "jan.xlsx",
                                "mimeType": "application/octet-stream",
                            }
                        ],
                        "nextPageToken": "next-page",
                    }
                ),
                FakeResponse(
                    data={
                        "files": [
                            {"id": "two", "name": "fev.csv", "mimeType": "text/csv"}
                        ]
                    }
                ),
            ]
        )

        files = drive_import.list_folder_files(session, "folder-id")

        self.assertEqual([file["id"] for file in files], ["one", "two"])
        assert session.calls[1][1] is not None
        self.assertEqual(session.calls[1][1]["pageToken"], "next-page")

    def test_rejects_incomplete_or_malformed_listing(self) -> None:
        for page in (
            {},
            {"files": [], "incompleteSearch": True},
            {"files": [{"name": "x.csv", "mimeType": "text/csv"}]},
            {"files": [None]},
        ):
            with (
                self.subTest(page=page),
                self.assertRaises(drive_import.DriveImportError),
            ):
                drive_import.list_folder_files(
                    FakeSession([FakeResponse(data=page)]), "folder"
                )

    def test_rejects_repeated_page_token(self) -> None:
        page = {"files": [], "nextPageToken": "repeat"}
        with self.assertRaises(drive_import.DriveImportError):
            drive_import.list_folder_files(
                FakeSession([FakeResponse(data=page), FakeResponse(data=page)]),
                "folder",
            )

    def test_retry_only_transient_errors(self) -> None:
        for status, expected in ((403, False), (404, False), (429, True), (503, True)):
            response = requests.Response()
            response.status_code = status
            try:
                raise drive_import.DriveImportError("erro") from requests.HTTPError(
                    response=response
                )
            except drive_import.DriveImportError as error:
                self.assertEqual(drive_import._is_transient_error(error), expected)

    def test_fingerprint_depends_on_import_options(self) -> None:
        file = {
            "id": "one",
            "name": "data.csv",
            "mimeType": "text/csv",
            "modifiedTime": "now",
        }
        default = drive_import._file_fingerprint(file)
        self.assertNotEqual(
            default, drive_import._file_fingerprint(file, csv_origin="Gpon")
        )
        self.assertNotEqual(
            default, drive_import._file_fingerprint(file, default_date=date(2026, 1, 1))
        )

    def test_import_drive_folder_parses_csv_points(self) -> None:
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
                        "Técnico;Data;Pontos\nAna;11/2026;125,5\nAna;11/2026;10\n"
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

    def test_snapshot_tracks_files_and_successfully_refreshed_ids(self) -> None:
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

    def test_snapshot_skips_unchanged_files(self) -> None:
        drive_file = {
            "id": "file-id",
            "name": "producao.csv",
            "mimeType": "text/csv",
            "modifiedTime": "2026-11-06T12:00:00Z",
        }
        session = FakeSession([FakeResponse(data={"files": [drive_file]})])
        fingerprint = drive_import._file_fingerprint(drive_file)
        assert fingerprint is not None

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

    def test_file_with_parse_issues_still_counts_as_refreshed(self) -> None:
        drive_file = {
            "id": "file-id",
            "name": "producao.csv",
            "mimeType": "text/csv",
            "modifiedTime": "2026-11-06T12:00:00Z",
        }
        session = FakeSession([FakeResponse(data={"files": [drive_file]})])

        with (
            patch("drive_import.create_drive_session", return_value=session),
            patch(
                "drive_import.download_file",
                return_value=(
                    "producao [file-id].csv",
                    b"Tecnico;Data;Pontos;Contrato\nAna;11/2026;abc;001\nBia;11/2026;10;002\n",
                ),
            ),
        ):
            result = drive_import.import_drive_folder_snapshot({}, "folder-id")

        # A linha com pontos inválidos gera issue, mas o arquivo baixou e
        # processou: não deve rebaixar o fingerprint a cada sincronização.
        self.assertEqual(result.successful_files, 1)
        self.assertEqual(result.refreshed_file_ids, {"file-id"})
        self.assertTrue(result.issues)

    def test_snapshot_reimports_files_after_contract_parser_change(self) -> None:
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

    def test_snapshot_downloads_files_in_parallel(self) -> None:
        files = [
            {"id": "one", "name": "one.csv", "mimeType": "text/csv"},
            {"id": "two", "name": "two.csv", "mimeType": "text/csv"},
        ]
        session = FakeSession([FakeResponse(data={"files": files})])
        barrier = Barrier(2)

        def download_file(
            _session: object, drive_file: dict[str, str]
        ) -> tuple[str, bytes]:
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

    def test_reuses_worker_session_and_listing_token(self) -> None:
        files = [
            {"id": str(i), "name": f"{i}.csv", "mimeType": "text/csv"} for i in range(4)
        ]

        class Credentials:
            token = "listing-token"

        class Session:
            def __init__(self, credentials: Credentials) -> None:
                self.credentials = credentials
                self.closed = False

            def close(self) -> None:
                self.closed = True

        listing = Session(Credentials())
        workers: list[Session] = []

        def new_worker(credentials: Credentials) -> Session:
            worker = Session(credentials)
            workers.append(worker)
            return worker

        with (
            patch("drive_import.create_drive_session", return_value=listing),
            patch("drive_import.list_folder_files", return_value=files),
            patch("drive_import.AuthorizedSession", side_effect=new_worker),
            patch("drive_import.MAX_PARALLEL_DOWNLOADS", 1),
            patch(
                "drive_import.download_file",
                return_value=("data.csv", b"Tecnico;Data;Pontos\nAna;11/2026;10\n"),
            ),
        ):
            result = drive_import.import_drive_folder_snapshot({}, "folder")

        self.assertEqual(result.successful_files, 4)
        self.assertEqual(len(workers), 1)
        self.assertIsNot(workers[0].credentials, listing.credentials)
        self.assertEqual(workers[0].credentials.token, "listing-token")
        self.assertTrue(listing.closed)
        self.assertTrue(workers[0].closed)

    def test_worker_sessions_closed_on_unexpected_error(self) -> None:
        class Session:
            credentials = object()
            closed = False

            def close(self) -> None:
                self.closed = True

        listing, worker = Session(), Session()
        files = [{"id": "one", "name": "one.csv", "mimeType": "text/csv"}]
        with (
            patch("drive_import.create_drive_session", return_value=listing),
            patch("drive_import.list_folder_files", return_value=files),
            patch("drive_import.AuthorizedSession", return_value=worker),
            patch("drive_import.download_file", side_effect=RuntimeError("failure")),
            self.assertRaises(RuntimeError),
        ):
            drive_import.import_drive_folder_snapshot({}, "folder")
        self.assertTrue(listing.closed)
        self.assertTrue(worker.closed)

    def test_unsupported_file_is_not_downloaded(self) -> None:
        session = FakeSession([])

        result = drive_import.download_file(
            session,
            {"id": "doc-id", "name": "readme.pdf", "mimeType": "application/pdf"},
        )

        self.assertIsNone(result)
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
