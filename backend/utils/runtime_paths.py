from __future__ import annotations

from pathlib import Path


def resolve_backend_root(anchor: str | Path) -> Path:
    current = Path(anchor).resolve()
    for base in [current.parent, *current.parents]:
        if (base / "main.py").is_file() and (base / "services").is_dir():
            return base
    raise RuntimeError(f"Could not resolve backend root from {current}")


def resolve_fastapi_root(anchor: str | Path) -> Path:
    return resolve_backend_root(anchor)


def resolve_pdf_scan_runtime_dir(anchor: str | Path) -> Path:
    backend_root = resolve_backend_root(anchor)
    runtime_dir = backend_root / "pdf_scan_runtime"
    if runtime_dir.is_dir() and (runtime_dir / "phase_a_lab.py").is_file():
        return runtime_dir
    raise RuntimeError(f"Could not resolve vendored pdf_scan_runtime directory from {backend_root}")


def resolve_pdf_scan_pipeline_script(anchor: str | Path) -> Path:
    backend_root = resolve_backend_root(anchor)
    script = backend_root / "run_pdf_scan_pipeline.py"
    if script.is_file():
        return script
    raise RuntimeError(f"Could not resolve run_pdf_scan_pipeline.py from {backend_root}")
