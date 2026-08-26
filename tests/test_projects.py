from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio import projects
from studio.executor import WorkflowExecutor
from studio.models import Workflow
from studio.repository import StudioRepository


class ProjectDirectoryTests(unittest.TestCase):
    def test_default_and_idempotent_project_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            original = projects.PROJECTS_ROOT
            projects.PROJECTS_ROOT = Path(directory) / "projects"
            try:
                self.assertEqual(projects.list_project_names(), ["default"])
                self.assertEqual(projects.validate_project_name("我的项目"), "我的项目")
                created = projects.project_directory("demo")
                self.assertTrue(created.is_dir())
                self.assertEqual(projects.project_directory("demo"), created)
                self.assertEqual(projects.list_project_names(), ["default", "demo"])
            finally:
                projects.PROJECTS_ROOT = original

    def test_project_name_rejects_paths(self):
        for value in ("", ".", "..", "../outside", "a\\b", "a/b"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    projects.validate_project_name(value)

    def test_unique_image_paths_use_project_and_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory) / "projects"
            repo = StudioRepository(Path(directory) / "studio.db")
            executor = WorkflowExecutor(repo)
            with patch("studio.executor.project_directory", lambda name: project_root / name):
                first = executor._unique_image_output_path(project_root / "demo")
                first.parent.mkdir(parents=True, exist_ok=True)
                first.write_bytes(b"first")
                second = executor._unique_image_output_path(project_root / "demo")
            self.assertNotEqual(first, second)
            self.assertRegex(first.name, r"^generate_image_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}_\d{3}(?:_\d{3})?\.jpg$")
            self.assertEqual(first.parent, project_root / "demo" / "character_images")

    def test_project_api_lists_default_and_reuses_existing(self):
        from fastapi.testclient import TestClient
        from studio.api import create_app

        with tempfile.TemporaryDirectory() as directory:
            original = projects.PROJECTS_ROOT
            projects.PROJECTS_ROOT = Path(directory) / "projects"
            try:
                client = TestClient(create_app())
                listed = client.get("/api/projects")
                self.assertEqual(listed.status_code, 200)
                self.assertEqual(listed.json()["projects"], ["default"])
                created = client.post("/api/projects", json={"name": "demo"})
                reused = client.post("/api/projects", json={"name": "demo"})
                self.assertEqual(created.status_code, 200)
                self.assertTrue(created.json()["created"])
                self.assertEqual(reused.status_code, 200)
                self.assertFalse(reused.json()["created"])
                invalid = client.post("/api/projects", json={"name": "../outside"})
                self.assertEqual(invalid.status_code, 422)
            finally:
                projects.PROJECTS_ROOT = original
    def test_executor_writes_generated_image_to_selected_project(self):
        class FakeImage:
            default_model = "fake-image"

            def generate_image_url(self, prompt, output_path, **kwargs):
                output_path = Path(output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"image")
                return output_path, "https://example.com/generated.jpg"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "projects"
            repo = StudioRepository(Path(directory) / "studio.db")
            workflow = Workflow.from_dict({
                "id": "selected-project",
                "project_name": "demo",
                "nodes": [{"id": "image", "type": "image_generate", "data": {}}],
            })
            executor = WorkflowExecutor(repo, image_client=FakeImage())
            with patch("studio.executor.project_directory", lambda name: root / name):
                run_id = executor.run(workflow, node_ids=["image"])
                for _ in range(100):
                    run = repo.get_run(run_id)
                    if run and run["status"] in {"succeeded", "failed"}:
                        break
                    import time
                    time.sleep(0.01)
            self.assertEqual(run["status"], "succeeded")
            result = run["results"]["image"]
            image_path = Path(result["path"])
            self.assertTrue(image_path.is_file())
            self.assertEqual(image_path.parent, root / "demo" / "character_images")
            self.assertRegex(image_path.name, r"^generate_image_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}_\d{3}(?:_\d{3})?\.jpg$")
    def test_workflow_project_name_defaults_for_old_payloads(self):
        self.assertEqual(Workflow.from_dict({"id": "old"}).project_name, "default")
        self.assertEqual(Workflow.from_dict({"id": "new", "project_name": "demo"}).to_dict()["project_name"], "demo")


if __name__ == "__main__":
    unittest.main()