from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.two_lane_sources.handoff import restore_handoff_bundle, upload_handoff_bundle


class _LocalLocation:
    def __init__(self, root: Path, rel: str) -> None:
        self.bucket = "local-test"
        self.object_name = rel
        self.uri = f"file://{(root / rel).resolve().as_posix()}"


class LocalArtifactStore:
    def __init__(self, root: Path, *, base_prefix: str = "two-lane-test") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.bucket_name = "local-test"
        self.base_prefix = str(base_prefix or "").strip().strip("/")

    def run_prefix(self, run_id: str) -> str:
        if self.base_prefix:
            return f"{self.base_prefix}/{str(run_id).strip()}"
        return str(run_id).strip()

    def _target(self, rel: str) -> Path:
        return (self.root / str(rel or "").strip().lstrip("/")).resolve()

    def upload_file(self, *, local_path: Path, path_or_uri: str, content_type: str | None = None) -> str:
        del content_type
        target = self._target(path_or_uri)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(local_path).resolve(), target)
        return target.as_uri()

    def upload_json(self, *, payload, path_or_uri: str) -> str:
        target = self._target(path_or_uri)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target.as_uri()

    def download_file(self, *, path_or_uri: str, local_path: Path) -> Path:
        source = Path(str(path_or_uri or "").replace("file:///", "")).resolve()
        target = Path(local_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target

    def download_json(self, *, path_or_uri: str):
        source = Path(str(path_or_uri or "").replace("file:///", "")).resolve()
        return json.loads(source.read_text(encoding="utf-8"))

    def location(self, path_or_uri: str):
        return _LocalLocation(self.root, str(path_or_uri or "").strip().lstrip("/"))

    def delete_run_prefix(self, run_id: str) -> int:
        prefix = self._target(self.run_prefix(run_id))
        if not prefix.exists():
            return 0
        files = [p for p in prefix.rglob("*") if p.is_file()]
        shutil.rmtree(prefix, ignore_errors=True)
        return len(files)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="two_lane_handoff_test_") as tmpdir:
        root = Path(tmpdir).resolve()
        run_dir = root / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "query_plan.json").write_text(json.dumps({"plan": 1}), encoding="utf-8")
        (run_dir / "openalex_queries.json").write_text(json.dumps({"openalex_queries": [{"query_string": "q"}]}), encoding="utf-8")
        (run_dir / "nested").mkdir(parents=True, exist_ok=True)
        (run_dir / "nested" / "logs.jsonl").write_text('{"ok":true}\n', encoding="utf-8")

        store = LocalArtifactStore(root / "artifacts")
        manifest = upload_handoff_bundle(
            run_dir=run_dir,
            artifact_store=store,
            run_id="run-123",
            pipeline_version="two_lane_v1",
            stage_name="preprocess",
        )

        restore_root = root / "restore"
        restored_dir = restore_handoff_bundle(
            artifact_store=store,
            manifest=manifest,
            work_root=restore_root,
        )

        restored_files = sorted(
            str(p.relative_to(restored_dir)).replace("\\", "/")
            for p in restored_dir.rglob("*")
            if p.is_file()
        )
        deleted_objects = store.delete_run_prefix("run-123")

        if sorted(restored_files) != ["nested/logs.jsonl", "openalex_queries.json", "query_plan.json"]:
            raise RuntimeError(f"Unexpected restored files: {restored_files}")
        if int(manifest.get("file_count") or 0) != 3:
            raise RuntimeError(f"Unexpected manifest file_count: {manifest.get('file_count')}")
        if int(deleted_objects) != 2:
            raise RuntimeError(f"Unexpected deleted object count: {deleted_objects}")

        result = {
            "ok": True,
            "manifest_stage": manifest.get("stage_name"),
            "manifest_file_count": int(manifest.get("file_count") or 0),
            "restored_files": restored_files,
            "deleted_objects": int(deleted_objects),
        }
        out_dir = Path(__file__).resolve().parents[1] / ".two_lane_artifacts" / "rate_limit_tests"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "test_two_lane_stage_handoff_latest.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
