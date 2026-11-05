import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import recipe_search.presentation.recipe_display_image as rdi


class BorrowedImageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.dir = self.directory.name
        rdi.close_image_connections()
        db = Path(self.dir) / "map.sqlite"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE fallback (recipeid INTEGER PRIMARY KEY, image_url TEXT NOT NULL, level TEXT, score REAL, image_recipeid INTEGER, image_name TEXT)"
        )
        con.executemany(
            "INSERT INTO fallback VALUES (?,?,?,?,?,?)",
            [
                (1, "https://img.test/a.jpg", "L1", 0.7, 10, "Cherry Pie"),
                (2, "https://img.test/a.jpg", "L2", 0.4, 10, "Cherry Pie"),
                (3, "javascript:alert(1)", "L2", 0.4, 11, "Bad"),
            ],
        )
        con.commit()
        con.close()
        self.old = rdi.BORROWED_DB
        rdi.BORROWED_DB = db
        rdi._local = threading.local()

    def tearDown(self):
        rdi.close_image_connections()
        rdi.BORROWED_DB = self.old
        rdi._local = threading.local()

    def test_shutdown_closes_and_next_lookup_reopens(self):
        con = rdi._connection()
        self.assertIs(con, rdi._connection())
        rdi.close_image_connections()
        rdi.close_image_connections()
        with self.assertRaises(sqlite3.ProgrammingError):
            con.execute("SELECT 1")
        self.assertEqual(rdi.borrowed_image({"recipeid": 1})["url"], "https://img.test/a.jpg")

    def test_app_shutdown_closes_mapping_connections(self):
        from fastapi.testclient import TestClient

        from recipe_search.api import search
        from recipe_search.api.app import app

        with patch.object(search, "warmup_retrieval"), TestClient(app):
            con = rdi._connection()
            self.assertIsNotNone(con)
        with self.assertRaises(sqlite3.ProgrammingError):
            con.execute("SELECT 1")

    def test_thread_exit_closes_its_connection(self):
        opened = []
        connect = sqlite3.connect

        def track(*args, **kwargs):
            con = connect(*args, **kwargs)
            opened.append(con)
            return con

        with patch.object(rdi.sqlite3, "connect", side_effect=track):
            thread = threading.Thread(target=lambda: rdi.borrowed_image({"recipeid": 1}))
            thread.start()
            thread.join()
        self.assertEqual(len(opened), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            opened[0].execute("SELECT 1")

    def test_original_photo_wins(self):
        image, source = rdi.choose_display_image(
            dict(recipeid=1, name="Berry pie", image_urls=["https://img.test/own.jpg"])
        )
        self.assertEqual((image, source), ("https://img.test/own.jpg", "original"))

    def test_borrowed_photo_is_labelled(self):
        out = rdi.enrich_recipe_for_display(dict(recipeid=1, name="Berry-Cherry Pie"))
        self.assertEqual(out["image_source"], "borrowed:L1")
        self.assertEqual(out["display_image_url"], "https://img.test/a.jpg")
        self.assertEqual(out["borrowed_image"]["name"], "Cherry Pie")
        self.assertFalse(out["has_original_image"])
        self.assertTrue(out["fallback_image_url"].endswith(".svg"))

    def test_unmapped_and_unsafe_urls_use_icon(self):
        for rid in (3, 99, None):
            with self.subTest(rid=rid):
                self.assertTrue(
                    rdi.choose_display_image(dict(recipeid=rid, name="Pie"))[1].startswith(
                        "fallback:"
                    )
                )

    def test_missing_mapping_file_is_harmless(self):
        rdi.BORROWED_DB = Path(self.dir) / "absent.sqlite"
        rdi._local = threading.local()
        self.assertTrue(
            rdi.choose_display_image(dict(recipeid=1, name="Pie"))[1].startswith("fallback:")
        )

    def test_same_borrowed_photo_once_per_page(self):
        page = rdi.dedupe_borrowed_images(
            [rdi.enrich_recipe_for_display(dict(recipeid=i, name="Pie")) for i in (1, 2)]
        )
        self.assertEqual(page[0]["image_source"], "borrowed:L1")
        self.assertTrue(page[1]["image_source"].startswith("fallback:"))
        self.assertIsNone(page[1]["borrowed_image"])
        self.assertEqual(page[1]["display_image_url"], page[1]["fallback_image_url"])


if __name__ == "__main__":
    unittest.main()
