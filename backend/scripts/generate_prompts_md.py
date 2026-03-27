from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _module_assignments(tree: ast.Module) -> dict[str, ast.AST]:
    assignments: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
    return assignments


def _resolve_node(node: ast.AST, assignments: dict[str, ast.AST]) -> Any:
    if isinstance(node, ast.Name):
        if node.id not in assignments:
            raise KeyError(f"Assignment not found: {node.id}")
        return _resolve_node(assignments[node.id], assignments)
    if isinstance(node, ast.Dict):
        return {
            _resolve_node(key, assignments): _resolve_node(value, assignments)
            for key, value in zip(node.keys, node.values)
        }
    if isinstance(node, ast.List):
        return [_resolve_node(item, assignments) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_resolve_node(item, assignments) for item in node.elts)
    return ast.literal_eval(node)


def _extract_module_assign(tree: ast.Module, name: str) -> Any:
    assignments = _module_assignments(tree)
    if name not in assignments:
        raise KeyError(f"Assignment not found: {name}")
    return _resolve_node(assignments[name], assignments)


def main() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    prompt_service_path = root_dir / "services" / "prompt_service.py"
    openai_service_path = root_dir / "services" / "openai_service.py"
    output_path = root_dir / "PROMPTS.md"

    prompt_service_tree = ast.parse(prompt_service_path.read_text(encoding="utf-8"))
    default_instructions: dict[str, str] = _extract_module_assign(
        prompt_service_tree, "DEFAULT_INSTRUCTIONS"
    )

    openai_service_tree = ast.parse(openai_service_path.read_text(encoding="utf-8"))
    summarize_system: str = _extract_module_assign(openai_service_tree, "SUMMARIZE_SYSTEM_MESSAGE")
    shorten_system: str = _extract_module_assign(openai_service_tree, "SHORTEN_SYSTEM_MESSAGE")
    lesefluss_system: str = _extract_module_assign(openai_service_tree, "LESEFLUSS_SYSTEM_MESSAGE")
    no_content_sentinel: str = _extract_module_assign(openai_service_tree, "NO_CONTENT_SENTINEL")

    process_quelle_system = (
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        "You can analyze both text and images provided. "
        "Think step-by-step to ensure correctness. "
        f"If the Quelle does NOT contain any useful information for the request, respond with the single token '{no_content_sentinel}' only. "
        "Otherwise, return only the final answer without any extra commentary."
    )

    combine_system = (
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
    )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    md = []
    md.append("# Prompt Inventory\n")
    md.append(f"_Generated at {generated_at} by `backend/scripts/generate_prompts_md.py`._\n")

    md.append("## Runtime prompt dumps\n")
    md.append(
        "In local development (`DEBUG=true`), when `DUMP_OPENAI_PROMPTS=true`, the backend writes a markdown file for every OpenAI request into `backend/.prompt_dumps/` (disabled on Cloud Run).\n"
    )
    md.append(
        "Each dump file separates `System Prompt` vs `Instructions` (user input) so you can iteratively improve prompts one-by-one.\n"
    )

    md.append("## System prompts (backend)\n")
    md.append("### `process_quelle`\n")
    md.append("```text\n" + process_quelle_system + "\n```\n")
    md.append("### `combine`\n")
    md.append("```text\n" + combine_system + "\n```\n")
    md.append("### `summary`\n")
    md.append("```text\n" + summarize_system + "\n```\n")
    md.append("### `shorten`\n")
    md.append("```text\n" + shorten_system + "\n```\n")
    md.append("### `lesefluss`\n")
    md.append("```text\n" + lesefluss_system + "\n```\n")

    md.append("## Instruction templates (defaults)\n")
    md.append(
        "These are the **default** instruction templates in `backend/services/prompt_service.py`.\n"
        "They can be overridden per-user via Firestore (`users/{userId}/promptTemplates` + `promptSettings/active`).\n"
    )

    for stage in ["process_quelle", "combine", "summary", "shorten", "lesefluss"]:
        md.append(f"### `{stage}`\n")
        md.append("```text\n" + default_instructions.get(stage, "") + "\n```\n")

    md.append("## Where each prompt is used\n")
    md.append("- Quelle processing: `backend/services/quelle_service.py` → `OpenAIService.process_quelle()`\n")
    md.append("- Combining: `backend/services/quelle_service.py` → `OpenAIService.combine_texts()`\n")
    md.append("- Summary/shorten/lesefluss: `backend/services/shorten_service.py`\n")
    md.append("- Text refinements: `backend/services/refinement_service.py` (reuses the same OpenAI calls)\n")

    output_path.write_text("\n".join(md), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
