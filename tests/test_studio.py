import tempfile
import unittest
from pathlib import Path

from studio.compiler import preview_workflow
from studio.models import Workflow
from studio.repository import StudioRepository
from studio.executor import WorkflowExecutor
from studio.validation import validate_workflow, topological_order
from studio.storage import image_bytes_to_data_url
from studio.api import create_app
from agents.video.generate import build_content_blocks
from agents.image.seedream_client import SeedreamClient


class StudioWorkflowTests(unittest.TestCase):
    def test_topological_order_and_preview(self):
        workflow = Workflow.from_dict({
            "id": "demo", "title": "Demo",
            "nodes": [
                {"id": "prompt", "type": "text_input", "data": {"text": "a fox"}},
                {"id": "video", "type": "video_generate", "data": {"mode": "text_to_video"}},
            ],
            "edges": [{"id": "edge", "source": "prompt", "target": "video", "source_handle": "text", "target_handle": "prompt"}],
        })
        self.assertTrue(validate_workflow(workflow).valid)
        self.assertEqual(topological_order(workflow), ["prompt", "video"])
        preview = preview_workflow(workflow)
        self.assertEqual(preview["payloads"][0]["content"][0]["type"], "text")

    def test_cycle_is_rejected(self):
        workflow = Workflow.from_dict({"title": "Cycle", "nodes": [
            {"id": "a", "type": "text_input"}, {"id": "b", "type": "output"}],
            "edges": [{"id": "1", "source": "a", "target": "b"}, {"id": "2", "source": "b", "target": "a"}]})
        result = validate_workflow(workflow)
        self.assertFalse(result.valid)
        self.assertTrue(any("cycle" in error.lower() for error in result.errors))

    def test_content_block_order(self):
        blocks = build_content_blocks("edit", ["https://a/image.jpg", "https://b/image.jpg"], "https://c/video.mp4")
        self.assertEqual([block["type"] for block in blocks], ["text", "image_url", "image_url", "video_url"])

    def test_preview_reuses_generated_image_result_url_for_video(self):
        workflow = Workflow.from_dict({
            "id": "generated-to-video", "title": "Generated To Video", "nodes": [
                {"id": "prompt", "type": "text_input", "data": {"text": "animate this"}},
                {"id": "image", "type": "image_generate", "data": {
                    "result": {"type": "image_result", "url": "https://cdn.example.com/generated.jpg"},
                }},
                {"id": "video", "type": "video_generate", "data": {}},
            ],
            "edges": [
                {"id": "prompt-image", "source": "prompt", "target": "image", "source_handle": "text", "target_handle": "prompt"},
                {"id": "image-video", "source": "image", "target": "video", "source_handle": "image", "target_handle": "image"},
            ],
        })
        payload = preview_workflow(workflow)["payloads"][1]
        self.assertEqual(payload["mode"], "image_to_video")
        self.assertEqual(payload["content"][0]["image_url"]["url"], "https://cdn.example.com/generated.jpg")

    def test_multiple_generated_image_results_preserve_order_for_video(self):
        workflow = Workflow.from_dict({
            "id": "generated-images", "title": "Generated Images", "nodes": [
                {"id": "a", "type": "image_generate", "data": {
                    "result": {"type": "image_result", "url": "https://cdn.example.com/a.jpg"},
                }},
                {"id": "b", "type": "image_generate", "data": {
                    "result": {"type": "image_result", "url": "https://cdn.example.com/b.jpg"},
                }},
                {"id": "video", "type": "video_generate", "data": {}},
            ],
            "edges": [
                {"id": "a-video", "source": "a", "target": "video", "source_handle": "image", "target_handle": "image"},
                {"id": "b-video", "source": "b", "target": "video", "source_handle": "image", "target_handle": "image"},
            ],
        })
        payload = preview_workflow(workflow)["payloads"][-1]
        urls = [block["image_url"]["url"] for block in payload["content"]]
        self.assertEqual(urls, ["https://cdn.example.com/a.jpg", "https://cdn.example.com/b.jpg"])

    def test_generated_image_without_url_is_uploaded_before_video_generation(self):
        class FakeImage:
            default_model = "fake-image"
            def generate_image_url(self, prompt, output_path, **kwargs):
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"fake-image")
                return Path(output_path), ""

        class FakeStorage:
            def __init__(self):
                self.uploaded = None
            def upload(self, path):
                self.uploaded = Path(path)
                return "https://cdn.example.com/uploads/generated.jpg"
            def resolve(self, value):
                return value

        class FakeVideo:
            default_model = "fake-video"
            def __init__(self):
                self.content = None
            def generate(self, *, content, output_path, **kwargs):
                self.content = content
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"fake-video")
                return Path(output_path)

        workflow = Workflow.from_dict({
            "id": "generated-no-url", "title": "Generated No URL", "nodes": [
                {"id": "image", "type": "image_generate", "data": {}},
                {"id": "video", "type": "video_generate", "data": {}},
            ],
            "edges": [{"id": "image-video", "source": "image", "target": "video", "source_handle": "image", "target_handle": "image"}],
        })
        storage = FakeStorage()
        video = FakeVideo()
        with tempfile.TemporaryDirectory() as directory:
            repo = StudioRepository(Path(directory) / "studio.db")
            executor = WorkflowExecutor(repo, image_client=FakeImage(), video_client=video, storage=storage)
            run_id = executor.run(workflow, node_ids=["video"])
            for _ in range(100):
                run = repo.get_run(run_id)
                if run and run["status"] in {"succeeded", "failed"}:
                    break
                import time
                time.sleep(0.01)
        self.assertEqual(run["status"], "succeeded")
        self.assertIsNotNone(storage.uploaded)
        self.assertEqual(video.content[0]["image_url"]["url"], "https://cdn.example.com/uploads/generated.jpg")

    def test_local_image_path_is_uploaded_before_video_generation(self):
        class FakeStorage:
            def __init__(self):
                self.resolved = []
            def resolve(self, value):
                self.resolved.append(str(value))
                return "https://cdn.example.com/uploads/source.png"

        class FakeVideo:
            default_model = "fake-video"
            def __init__(self):
                self.content = None
            def generate(self, *, content, output_path, **kwargs):
                self.content = content
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"fake-video")
                return Path(output_path)

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            source.write_bytes(b"image-bytes")
            workflow = Workflow.from_dict({
                "id": "local-image-video", "title": "Local Image Video", "nodes": [
                    {"id": "asset", "type": "image_input", "data": {"path": str(source)}},
                    {"id": "video", "type": "video_generate", "data": {}},
                ],
                "edges": [{"id": "asset-video", "source": "asset", "target": "video", "source_handle": "image", "target_handle": "image"}],
            })
            storage = FakeStorage()
            video = FakeVideo()
            repo = StudioRepository(Path(directory) / "studio.db")
            executor = WorkflowExecutor(repo, video_client=video, storage=storage)
            run_id = executor.run(workflow, node_ids=["video"])
            for _ in range(100):
                run = repo.get_run(run_id)
                if run and run["status"] in {"succeeded", "failed"}:
                    break
                import time
                time.sleep(0.01)
            self.assertEqual(run["status"], "succeeded")
            self.assertEqual(storage.resolved, [str(source)])
            self.assertEqual(video.content[0]["image_url"]["url"], "https://cdn.example.com/uploads/source.png")

    def test_upload_endpoint_uses_public_storage_url(self):
        from fastapi.testclient import TestClient
        import studio.api as studio_api

        class FakeStorage:
            def upload(self, path):
                self.path = Path(path)
                return "https://cdn.example.com/uploads/source.png"

        provider = FakeStorage()
        original_provider = studio_api.configured_provider
        studio_api.configured_provider = lambda: provider
        try:
            response = TestClient(studio_api.create_app()).post(
                "/api/assets/upload",
                files={"file": ("source.png", b"image-bytes", "image/png")},
            )
        finally:
            studio_api.configured_provider = original_provider
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["url"], "https://cdn.example.com/uploads/source.png")
        self.assertEqual(provider.path.name, "source.png")

    def test_repository_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = StudioRepository(Path(directory) / "studio.db")
            workflow = Workflow(title="Persisted")
            repo.save_workflow(workflow)
            loaded = repo.get_workflow(workflow.id)
            self.assertEqual(loaded.title, "Persisted")

    def test_single_generation_runs_with_ancestors_and_persists_result(self):
        class FakeImage:
            default_model = "fake-image"
            def generate_image_url(self, prompt, output_path, **kwargs):
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"fake-image")
                return Path(output_path), "https://example.com/generated.jpg"

        class FakeVideo:
            default_model = "fake-video"

        workflow = Workflow.from_dict({
            "id": "single", "title": "Single", "nodes": [
                {"id": "prompt", "type": "text_input", "data": {"text": "a fox"}},
                {"id": "image", "type": "image_generate", "data": {"model": "fake-image"}},
            ], "edges": [{"id": "edge", "source": "prompt", "target": "image", "source_handle": "text", "target_handle": "prompt"}],
        })
        with tempfile.TemporaryDirectory() as directory:
            repo = StudioRepository(Path(directory) / "studio.db")
            executor = WorkflowExecutor(repo, image_client=FakeImage(), video_client=FakeVideo())
            run_id = executor.run(workflow, node_ids=["image"])
            for _ in range(100):
                run = repo.get_run(run_id)
                if run and run["status"] in {"succeeded", "failed"}:
                    break
                import time
                time.sleep(0.01)
            self.assertEqual(run["status"], "succeeded")
            self.assertEqual(run["results"]["image"]["type"], "image_result")

    def test_generated_image_dict_is_compiled_as_single_video_image_url(self):
        class FakeImage:
            default_model = "fake-image"

            def generate_image_url(self, prompt, output_path, **kwargs):
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"fake-image")
                return Path(output_path), "https://example.com/generated.jpg"

        class FakeVideo:
            default_model = "fake-video"

            def __init__(self):
                self.content = None

            def generate(self, *, content, output_path, **kwargs):
                self.content = content
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"fake-video")
                return Path(output_path)

        workflow = Workflow.from_dict({
            "id": "image-to-video", "title": "Image to Video", "nodes": [
                {"id": "prompt", "type": "text_input", "data": {"text": "animate it"}},
                {"id": "image", "type": "image_generate", "data": {}},
                {"id": "video", "type": "video_generate", "data": {}},
            ],
            "edges": [
                {"id": "prompt-image", "source": "prompt", "target": "image", "source_handle": "text", "target_handle": "prompt"},
                {"id": "image-video", "source": "image", "target": "video", "source_handle": "image_result", "target_handle": "image"},
            ],
        })
        fake_video = FakeVideo()
        with tempfile.TemporaryDirectory() as directory:
            repo = StudioRepository(Path(directory) / "studio.db")
            executor = WorkflowExecutor(repo, image_client=FakeImage(), video_client=fake_video)
            run_id = executor.run(workflow, node_ids=["video"])
            for _ in range(100):
                run = repo.get_run(run_id)
                if run and run["status"] in {"succeeded", "failed"}:
                    break
                import time
                time.sleep(0.01)
            self.assertEqual(run["status"], "succeeded")
            image_blocks = [block for block in fake_video.content if block["type"] == "image_url"]
            self.assertEqual(len(image_blocks), 1)
            self.assertEqual(image_blocks[0]["image_url"]["url"], "https://example.com/generated.jpg")
            self.assertNotIn(image_blocks[0]["image_url"]["url"], {"type", "path", "url"})

    def test_preview_preserves_order_for_multiple_image_results(self):
        workflow = Workflow.from_dict({
            "id": "multi-image", "title": "Multi Image", "nodes": [
                {"id": "a", "type": "image_input", "data": {"url": "https://example.com/a.jpg"}},
                {"id": "b", "type": "image_input", "data": {"url": "https://example.com/b.jpg"}},
                {"id": "video", "type": "video_generate", "data": {}},
            ],
            "edges": [
                {"id": "a-video", "source": "a", "target": "video", "source_handle": "image", "target_handle": "image"},
                {"id": "b-video", "source": "b", "target": "video", "source_handle": "image", "target_handle": "image"},
            ],
        })
        payload = preview_workflow(workflow)["payloads"][0]
        image_urls = [block["image_url"]["url"] for block in payload["content"] if block["type"] == "image_url"]
        self.assertEqual(image_urls, ["https://example.com/a.jpg", "https://example.com/b.jpg"])

    def test_inline_local_image_is_accepted_for_image_to_image(self):
        inline_image = "data:image/png;base64,AA=="

        class FakeImage:
            default_model = "fake-image"

            def __init__(self):
                self.reference_image = None

            def generate_image_url(self, prompt, output_path, **kwargs):
                self.reference_image = kwargs.get("reference_image")
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"fake-image")
                return Path(output_path), "https://example.com/generated.jpg"

        workflow = Workflow.from_dict({
            "id": "inline-image", "title": "Inline Image", "nodes": [
                {"id": "asset", "type": "image_input", "data": {"url": inline_image}},
                {"id": "image", "type": "image_generate", "data": {"prompt": "restyle this"}},
            ],
            "edges": [{"id": "asset-image", "source": "asset", "target": "image", "source_handle": "image", "target_handle": "reference"}],
        })
        self.assertTrue(validate_workflow(workflow, require_public_assets=True).valid)
        preview = preview_workflow(workflow)
        self.assertEqual(preview["payloads"][0]["image"], inline_image)
        fake_image = FakeImage()
        with tempfile.TemporaryDirectory() as directory:
            repo = StudioRepository(Path(directory) / "studio.db")
            executor = WorkflowExecutor(repo, image_client=fake_image)
            run_id = executor.run(workflow, node_ids=["image"])
            for _ in range(100):
                run = repo.get_run(run_id)
                if run and run["status"] in {"succeeded", "failed"}:
                    break
                import time
                time.sleep(0.01)
            self.assertEqual(run["status"], "succeeded")
            self.assertEqual(fake_image.reference_image, inline_image)

    def test_inline_local_image_is_rejected_for_direct_video_input(self):
        workflow = Workflow.from_dict({
            "id": "inline-video", "title": "Inline Video", "nodes": [
                {"id": "asset", "type": "image_input", "data": {"url": "data:image/png;base64,AA=="}},
                {"id": "video", "type": "video_generate", "data": {}},
            ],
            "edges": [{"id": "asset-video", "source": "asset", "target": "video", "source_handle": "image", "target_handle": "image"}],
        })
        result = validate_workflow(workflow, require_public_assets=True)
        self.assertFalse(result.valid)
        self.assertTrue(any("Seedance" in error for error in result.errors))

    def test_local_image_file_is_encoded_for_image_to_image(self):
        class FakeImage:
            default_model = "fake-image"

            def __init__(self):
                self.reference_image = None

            def generate_image_url(self, prompt, output_path, **kwargs):
                self.reference_image = kwargs.get("reference_image")
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"fake-image")
                return Path(output_path), "https://example.com/generated.jpg"

        workflow = Workflow.from_dict({
            "id": "local-file", "title": "Local File", "nodes": [
                {"id": "asset", "type": "image_input", "data": {}},
                {"id": "image", "type": "image_generate", "data": {"prompt": "restyle this"}},
            ],
            "edges": [{"id": "asset-image", "source": "asset", "target": "image", "source_handle": "image", "target_handle": "reference"}],
        })
        fake_image = FakeImage()
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "source.png"
            image_path.write_bytes(b"not-a-real-png-but-valid-for-encoding")
            workflow.node_map()["asset"].data["path"] = str(image_path)
            repo = StudioRepository(Path(directory) / "studio.db")
            executor = WorkflowExecutor(repo, image_client=fake_image)
            run_id = executor.run(workflow, node_ids=["image"])
            for _ in range(100):
                run = repo.get_run(run_id)
                if run and run["status"] in {"succeeded", "failed"}:
                    break
                import time
                time.sleep(0.01)
            self.assertEqual(run["status"], "succeeded")
            self.assertEqual(fake_image.reference_image, image_bytes_to_data_url(image_path.read_bytes(), filename="source.png"))

    def test_preview_rejects_inline_image_for_video_before_run(self):
        from fastapi.testclient import TestClient

        workflow = {
            "id": "inline-preview", "title": "Inline Preview", "nodes": [
                {"id": "asset", "type": "image_input", "data": {"url": "data:image/png;base64,AA=="}},
                {"id": "video", "type": "video_generate", "data": {}},
            ],
            "edges": [{"id": "asset-video", "source": "asset", "target": "video", "source_handle": "image", "target_handle": "image"}],
        }
        client = TestClient(create_app())
        response = client.post("/api/workflows/inline-preview/preview", json=workflow)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertFalse(result["valid"])
        self.assertTrue(any("public" in error.lower() for error in result["errors"]))

        # The node-level UI action uses /validate before submitting generation.
        validation = client.post("/api/workflows/inline-preview/validate", json=workflow)
        self.assertEqual(validation.status_code, 200)
        self.assertFalse(validation.json()["valid"])

    def test_upload_endpoint_returns_inline_image_without_storage_provider(self):
        from fastapi.testclient import TestClient

        response = TestClient(create_app()).post(
            "/api/assets/upload",
            files={"file": ("source.png", b"image-bytes", "image/png")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["url"], "data:image/png;base64,aW1hZ2UtYnl0ZXM=")

    def test_multiple_image_references_preserve_order_for_seedream(self):
        class FakeImage:
            default_model = "fake-image"

            def __init__(self):
                self.reference_image = None

            def generate_image_url(self, prompt, output_path, **kwargs):
                self.reference_image = kwargs.get("reference_image")
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"fake-image")
                return Path(output_path), "https://example.com/generated.jpg"

        workflow = Workflow.from_dict({
            "id": "multi-reference", "title": "Multi Reference", "nodes": [
                {"id": "a", "type": "image_input", "data": {"url": "https://example.com/a.jpg"}},
                {"id": "b", "type": "image_input", "data": {"url": "https://example.com/b.jpg"}},
                {"id": "image", "type": "image_generate", "data": {"prompt": "combine 图1 and 图2"}},
            ],
            "edges": [
                {"id": "a-image", "source": "a", "target": "image", "source_handle": "image", "target_handle": "reference"},
                {"id": "b-image", "source": "b", "target": "image", "source_handle": "image", "target_handle": "reference"},
            ],
        })
        preview = preview_workflow(workflow)
        self.assertEqual(preview["payloads"][0]["image"], ["https://example.com/a.jpg", "https://example.com/b.jpg"])
        fake_image = FakeImage()
        with tempfile.TemporaryDirectory() as directory:
            repo = StudioRepository(Path(directory) / "studio.db")
            executor = WorkflowExecutor(repo, image_client=fake_image)
            run_id = executor.run(workflow, node_ids=["image"])
            for _ in range(100):
                run = repo.get_run(run_id)
                if run and run["status"] in {"succeeded", "failed"}:
                    break
                import time
                time.sleep(0.01)
            self.assertEqual(run["status"], "succeeded")
            self.assertEqual(fake_image.reference_image, ["https://example.com/a.jpg", "https://example.com/b.jpg"])

    def test_seedream_client_accepts_ordered_reference_image_list(self):
        class FakeImages:
            def __init__(self):
                self.kwargs = None

            def generate(self, **kwargs):
                self.kwargs = kwargs
                return type("Result", (), {"data": [type("Image", (), {"url": "https://example.com/result.jpg"})()]})()

        client = SeedreamClient.__new__(SeedreamClient)
        client._defaults = {}
        client._models = {"default": "fake-image"}
        client._client = type("ArkClient", (), {"images": FakeImages()})()
        client._request_log_path = None
        client._result_log_path = None
        result = client.generate_image(
            prompt="combine 图1 and 图2",
            reference_image=["https://example.com/a.jpg", "https://example.com/b.jpg"],
        )
        self.assertEqual(result, "https://example.com/result.jpg")
        self.assertEqual(client._client.images.kwargs["image"], ["https://example.com/a.jpg", "https://example.com/b.jpg"])


if __name__ == "__main__":
    unittest.main()
