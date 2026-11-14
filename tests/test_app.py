import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ts-test-"))
os.environ.setdefault("BASE_URL", "http://testserver")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi.testclient import TestClient  # noqa: E402

from app import config, posting, tiktok  # noqa: E402
from app.main import app  # noqa: E402


class ChunkPlanTests(unittest.TestCase):
    def test_small_file_is_one_chunk(self):
        self.assertEqual(tiktok.chunk_plan(3 * 1024 * 1024), (3 * 1024 * 1024, 1))

    def test_large_file_uses_tiktok_chunk_limits(self):
        size = 200 * 1024 * 1024
        chunk, count = tiktok.chunk_plan(size)
        self.assertGreaterEqual(chunk, tiktok.MIN_CHUNK)
        self.assertLessEqual(chunk, tiktok.MAX_CHUNK)
        self.assertEqual(count, (size + chunk - 1) // chunk)

    def test_empty_file_rejected(self):
        with self.assertRaises(tiktok.TikTokError):
            tiktok.chunk_plan(0)


class DemoStatusTests(unittest.TestCase):
    def test_inbox_finishes_in_inbox(self):
        post = {"mode": "inbox", "created_at": 0}
        self.assertEqual(posting.demo_status(post), "SEND_TO_USER_INBOX")

    def test_direct_finishes_published(self):
        post = {"mode": "direct", "created_at": 0}
        self.assertEqual(posting.demo_status(post), "PUBLISH_COMPLETE")


class WebFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_landing_and_policies(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/privacy.html").status_code, 200)
        self.assertEqual(self.client.get("/terms.html").status_code, 200)
        self.assertEqual(self.client.get("/healthz").json()["ok"], True)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_tiktok_domain_verification_file(self):
        name = "tiktokwGTZ1z4TGFKydRugLlWeQNeAOjAXOYyd.txt"
        response = self.client.get(f"/{name}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.text.strip())

    def test_oauth_demo_and_upload(self):
        response = self.client.get("/auth/tiktok", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        state = response.headers["location"].split("state=")[1]

        consent = self.client.get(f"/demo/consent?state={state}")
        self.assertEqual(consent.status_code, 200)

        callback = self.client.get(
            f"/auth/tiktok/callback?code=demo&state={state}",
            follow_redirects=False,
        )
        self.assertEqual(callback.status_code, 303)

        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("Video Scheduler Demo", dashboard.text)

        sample = Path(config.BASE_DIR) / "demo" / "sample.mp4"
        with sample.open("rb") as handle:
            upload = self.client.post(
                "/api/upload",
                files={"file": ("sample.mp4", handle, "video/mp4")},
                data={
                    "title": "unit test",
                    "privacy_level": "SELF_ONLY",
                    "mode": "inbox",
                },
            )
        self.assertEqual(upload.status_code, 200, upload.text)
        post_id = upload.json()["post"]["id"]

        post = self.client.get(f"/api/posts/{post_id}").json()
        self.assertIn(post["status"], posting.STATUS_RU)


if __name__ == "__main__":
    unittest.main()
