from __future__ import annotations

from pathlib import Path


def resolve_fastapi_root(anchor: str | Path) -> Path:
    current = Path(anchor).resolve()
    for base in [current.parent, *current.parents]:
        if (base / "main.py").is_file() and (base / "services").is_dir():
            return base
    raise RuntimeError(f"Could not resolve FastAPI root from {current}")


def resolve_pdf_scan_dir(anchor: str | Path) -> Path:
    current = Path(anchor).resolve()
    for base in [current.parent, *current.parents]:
        candidate = base / "pdf-scan"
        if candidate.is_dir() and (candidate / "phase_a_lab.py").is_file():
            return candidate
        if base.name == "pdf-scan" and (base / "phase_a_lab.py").is_file():
            return base
    raise RuntimeError(f"Could not resolve pdf-scan directory from {current}")


def resolve_pdf_scan_pipeline_script(anchor: str | Path) -> Path:
    fastapi_root = resolve_fastapi_root(anchor)
    script = fastapi_root / "run_pdf_scan_pipeline.py"
    if script.is_file():
        return script
    raise RuntimeError(f"Could not resolve run_pdf_scan_pipeline.py from {fastapi_root}")
