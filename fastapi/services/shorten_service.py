from services.firebase_service import firebase_service
from services.openai_service import openai_service
from services.cost_service import get_cost_service, TokenUsage
from services.credits_service import get_credits_service
from services.user_key_service import user_key_service
from services.prompt_service import prompt_service
import logging
import asyncio
import uuid
from datetime import datetime
import services.openai_service as openai_module
from typing import Optional, List, Tuple, Dict

logger = logging.getLogger(__name__)


class ShortenService:
    """Service for shortening and deduplicating Kapitel texts"""

    def __init__(self):
        pass

    async def get_latest_text_for_kapitel(
        self,
        user_id: str,
        kapitel_id: str,
    ) -> Tuple[str, str, str]:
        """
        Get the latest text for a Kapitel.
        Priority: lesefluss > shortened > combined

        Returns:
            tuple: (text_content, run_id, text_type)
            where text_type is 'lesefluss' | 'shortened' | 'combined'

        Raises:
            ValueError: If no text is found
        """
        logger.info(f"Getting latest text for Kapitel {kapitel_id}")

        kapitel_doc = await firebase_service.get_kapitel(user_id, kapitel_id)
        active_run_id = str((kapitel_doc or {}).get("activeRunId") or "").strip()

        # Get all runs for this Kapitel
        runs = await firebase_service.get_kapitel_runs(user_id, kapitel_id)

        if not runs:
            raise ValueError(f"No runs found for Kapitel {kapitel_id}")

        # Sort by createdAt (most recent first)
        sorted_runs = sorted(
            runs,
            key=lambda r: r.get("createdAt") or datetime(1970, 1, 1),
            reverse=True,
        )

        if active_run_id:
            active_run = next((r for r in sorted_runs if str(r.get("id")) == active_run_id), None)
            if active_run:
                sorted_runs = [active_run]

        # Try to find text with priority: lesefluss > shortened > combined
        for run in sorted_runs:
            run_id = run['id']

            # 1. Check for lesefluss text FIRST
            lesefluss = await firebase_service.get_lesefluss_result(user_id, kapitel_id, run_id)
            if lesefluss and (lesefluss.get("content") or "").strip():
                logger.info(f"Found lesefluss text for Kapitel {kapitel_id} in run {run_id}")
                return (lesefluss["content"], run_id, "lesefluss")

            # 2. Check for shortened text SECOND
            shortened = await firebase_service.get_shortened_result(user_id, kapitel_id, run_id)
            if shortened and (shortened.get("content") or "").strip():
                logger.info(f"Found shortened text for Kapitel {kapitel_id} in run {run_id}")
                return (shortened["content"], run_id, "shortened")

            # 3. Check for combined text LAST
            combined = await firebase_service.get_combined_result(user_id, kapitel_id, run_id)
            if combined and (combined.get("content") or "").strip():
                logger.info(f"Found combined text for Kapitel {kapitel_id} in run {run_id}")
                return (combined["content"], run_id, "combined")

        raise ValueError(f"No text found for Kapitel {kapitel_id}")

    async def is_summary_valid(
        self,
        summary: dict,
        current_run_id: str,
        current_text_type: str
    ) -> bool:
        """
        Check if a cached summary is still valid.

        Valid if: same run AND same text type
        text_type can be: 'combined' | 'shortened' | 'lesefluss'
        """
        source_run_id = summary.get("sourceRunId")
        source_type = summary.get("sourceType")

        is_valid = (source_run_id == current_run_id and source_type == current_text_type)

        logger.info(
            f"Summary validation: sourceRunId={source_run_id}, sourceType={source_type}, "
            f"currentRunId={current_run_id}, currentType={current_text_type} -> {is_valid}"
        )

        return is_valid

    async def get_or_create_summary(
        self,
        user_id: str,
        target_kapitel_id: str,
        target_run_id: str,
        source_kapitel_id: str,
        model: str,
        api_key: str,
        key_source: str,
        user_action_id: str,
    ) -> str:
        """
        Get cached summary or create new one.

        Returns:
            str: The summary content
        """
        logger.info(f"Getting/creating summary for Kapitel {source_kapitel_id}")

        # Get the latest text for the source Kapitel
        try:
            source_text, source_run_id, source_type = await self.get_latest_text_for_kapitel(
                user_id, source_kapitel_id
            )
        except ValueError as e:
            logger.warning(f"Could not get text for Kapitel {source_kapitel_id}: {e}")
            raise ValueError(f"Kapitel {source_kapitel_id} has no processable text")

        # Check if we have a cached summary
        cached_summary = await firebase_service.get_summary_result(
            user_id, target_kapitel_id, target_run_id, source_kapitel_id
        )

        if cached_summary:
            # Validate the cache
            is_valid = await self.is_summary_valid(
                cached_summary, source_run_id, source_type
            )

            if is_valid:
                logger.info(f"Using cached summary for Kapitel {source_kapitel_id}")
                return cached_summary["content"]
            else:
                logger.info(f"Cached summary invalid for Kapitel {source_kapitel_id}, regenerating")

        # Generate new summary
        logger.info(f"Generating new summary for Kapitel {source_kapitel_id}")
        await firebase_service.mark_summary_running(
            user_id,
            target_kapitel_id,
            target_run_id,
            source_kapitel_id,
            source_run_id=source_run_id,
            source_type=source_type,
            model=model,
            key_source=key_source,
        )

        try:
            instructions = await prompt_service.get_rendered_instructions(
                user_id, "summary", {"KAPITELTEXT": source_text}
            )
            summary_template_id = await firebase_service.get_active_prompt_id(user_id, "summary")
            summary_template_id = (summary_template_id or "").strip() or "default"
            summary_system_prompt = await prompt_service.get_system_prompt_for_template(
                stage="summary",
                template_id=summary_template_id,
            )
            await get_credits_service(firebase_service).assert_not_negative_balance(user_id)

            summary_content, usage = await self.summarize_text(
                source_text,
                model,
                source_kapitel_id,
                api_key=api_key,
                instructions=instructions,
                system_prompt=summary_system_prompt,
            )
            input_tokens = int(usage.get("prompt_tokens", 0))
            cached_input_tokens = int(usage.get("prompt_tokens_details", {}).get("cached_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))

            # Calculate cost and log immutable operation (costMetrics)
            cost_service = get_cost_service(firebase_service)
            usage_obj = TokenUsage.from_any(input_tokens, cached_input_tokens, output_tokens)
            cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(
                model=model,
                usage=usage_obj,
            )

            target_kapitel = await firebase_service.get_kapitel(user_id, target_kapitel_id)
            projekt_id = (target_kapitel or {}).get("projektId")

            projekt_snapshot = None
            if projekt_id:
                project = await firebase_service.get_project(user_id, projekt_id)
                if project:
                    projekt_snapshot = {
                        "id": projekt_id,
                        "name": project.get("name"),
                        "archived": bool(project.get("archived", False)),
                    }

            kapitel_snapshot = (
                {
                    "id": target_kapitel_id,
                    "nummer": (target_kapitel or {}).get("nummer", "?"),
                    "title": (target_kapitel or {}).get("title", "Untitled"),
                }
                if target_kapitel
                else None
            )

            run_snapshot = {
                "id": target_run_id,
                "index": None,
            }

            await cost_service.log_operation(
                operation_type="summary",
                user_id=user_id,
                user_action_id=user_action_id,
                operation_details={
                    "sourceKapitelId": source_kapitel_id,
                    "sourceRunId": source_run_id,
                    "sourceType": source_type,
                },
                model=model,
                usage=usage_obj,
                cost_breakdown=cost_breakdown,
                matched_model_key=matched_model,
                pricing=pricing,
                key_source=key_source,
                projekt_id=projekt_id,
                kapitel_id=target_kapitel_id,
                run_id=target_run_id,
                projekt_snapshot=projekt_snapshot,
                kapitel_snapshot=kapitel_snapshot,
                run_snapshot=run_snapshot,
            )

            cost = float(cost_breakdown.total_cost_usd)

            # Count words
            original_length = len(source_text.split())
            summary_length = len(summary_content.split())

            # Save the summary
            summary_data = {
                "content": summary_content,
                "sourceKapitelId": source_kapitel_id,
                "sourceRunId": source_run_id,
                "sourceType": source_type,
                "originalLength": original_length,
                "summaryLength": summary_length,
                "model": model,
                "usage": {
                    "inputTokens": input_tokens,
                    "cachedInputTokens": cached_input_tokens,
                    "outputTokens": output_tokens,
                    "reasoningTokens": 0,
                    "totalTokens": input_tokens + output_tokens,
                },
                "costUsd": float(cost),
                "keySource": key_source,
            }

            await firebase_service.save_summary_result(
                user_id, target_kapitel_id, target_run_id, source_kapitel_id, summary_data
            )

            logger.info(
                f"Summary created for Kapitel {source_kapitel_id}: "
                f"{original_length} -> {summary_length} words ({summary_length/original_length*100:.1f}%), "
                f"cost: ${cost:.4f}"
            )

            return summary_content
        except Exception:
            await firebase_service.mark_summary_error(
                user_id,
                target_kapitel_id,
                target_run_id,
                source_kapitel_id,
                key_source=key_source,
            )
            raise

    async def summarize_text(
        self,
        text: str,
        model: str,
        source_kapitel_id: str = None,
        api_key: Optional[str] = None,
        instructions: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> Tuple[str, dict]:
        """
        Summarize text to ~30% of original using OpenAI.

        Returns:
            tuple: (summary_content, usage_dict)
        """
        prompt = f"""### Aufgabe:
Fasse folgenden Text zusammen, sodass er auf ungefähr 30% Wörter vom Original Text kommt. Ziel dieser Zusammenfassung ist es, die Rhetorik und nebensächliche Informationen wegzulassen, aber die grundlegenden Informationen beizubehalten. Schreibe lieber Sätze die sich nicht flüssig lesen lassen, also ohne viele Stopwörter sind und integriere dafür aber mehr Information. Das Ziel ist einen Text der so kurz wie möglich aber auch so viele Informationen wie möglich hat. Quellen können weggelassen werden.

### Text:
{text}"""
        if instructions:
            prompt = instructions

        return await openai_service.summarize_kapitel(
            prompt,
            model,
            api_key=api_key,
            system_prompt=system_prompt,
        )

    async def build_gliederung(
        self,
        user_id: str,
        target_kapitel_id: str,
        context_kapitels: List[dict],
        summaries: Dict[str, str],
    ) -> str:
        """
        Build the Gliederung section with numbered Kapitels and summaries.

        Args:
            context_kapitels: List of Kapitel dicts with 'id', 'nummer', 'title'
            summaries: Dict mapping kapitel_id to summary_content

        Returns:
            str: Formatted Gliederung text
        """
        lines = []

        for kapitel in context_kapitels:
            kapitel_id = kapitel['id']
            nummer = kapitel.get('nummer', '?')
            title = kapitel.get('title', 'Untitled')

            # Add the Kapitel header
            nummer_str = str(nummer or "?").strip() or "?"
            if nummer_str.isdigit():
                lines.append(f"{nummer_str}. {title}")
            else:
                lines.append(f"{nummer_str} {title}")

            if kapitel_id == target_kapitel_id:
                lines.append("Das ist das Kapitel an dem wir gerade Arbeiten")
            elif kapitel_id in summaries:
                lines.append((summaries.get(kapitel_id) or "").strip())

            lines.append("")  # Empty line between Kapitels

        return "\n".join(lines)

    def _nummer_sort_key(self, nummer: str) -> tuple:
        parts = [p.strip() for p in str(nummer or "").split(".") if p.strip()]
        if not parts:
            return ((2, ""),)

        key = []
        for part in parts:
            digits = ""
            rest = ""
            for ch in part:
                if ch.isdigit() and not rest:
                    digits += ch
                else:
                    rest += ch

            if digits:
                key.append((0, int(digits)))
                if rest:
                    key.append((1, rest))
            else:
                key.append((1, part))

        return tuple(key)

    async def shorten_and_deduplicate(
        self,
        prompt: str,
        model: str,
        *,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        debug_prompt_dump_path: Optional[str] = None,
    ) -> Tuple[str, dict]:
        """
        Shorten and deduplicate text using OpenAI.

        Returns:
            tuple: (shortened_content, usage_dict)
        """
        return await openai_service.shorten_and_deduplicate(
            prompt,
            model,
            api_key=api_key,
            system_prompt=system_prompt,
            debug_prompt_dump_path=debug_prompt_dump_path,
        )

    async def process_shorten_request(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        context_kapitel_ids: List[str],
        model: str,
    ) -> None:
        """
        Main orchestration method for shortening a Kapitel.

        This method:
        1. Gets summaries for all context Kapitels (with caching)
        2. Builds the Gliederung
        3. Shortens the target Kapitel
        4. Saves the result
        """
        try:
            api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)
            user_action_id = str(uuid.uuid4())
            logger.info(
                f"Starting shorten process for Kapitel {kapitel_id}, run {run_id}, "
                f"with {len(context_kapitel_ids)} context Kapitels"
            )

            # Get the target Kapitel's combined text from the specific run
            combined = await firebase_service.get_combined_result(user_id, kapitel_id, run_id)
            if not combined or not (combined.get("content") or "").strip():
                raise ValueError(
                    f"No combined text found for Kapitel {kapitel_id} in run {run_id}. "
                    f"Please ensure the Kapitel has been processed first."
                )

            target_text = combined["content"]

            # Get the target Kapitel's run metadata for ueberschrift and thema
            run_data = await firebase_service.get_kapitel_run(user_id, kapitel_id, run_id)
            if not run_data:
                raise ValueError(f"Run {run_id} not found for Kapitel {kapitel_id}")

            # Enforce run-level model for all actions tied to this run.
            run_model = (run_data.get("model") or "").strip()
            if run_model:
                if model and model != run_model:
                    logger.info(
                        f"Overriding requested model '{model}' with run model '{run_model}' "
                        f"(Kapitel {kapitel_id}, run {run_id})"
                    )
                model = run_model
            else:
                logger.warning(
                    f"Run {run_id} for Kapitel {kapitel_id} has no model; falling back to requested model '{model}'"
                )

            ueberschrift = run_data.get('ueberschrift', 'Untitled')
            thema = run_data.get('thema', '')

            kapitel = await firebase_service.get_kapitel(user_id, kapitel_id)
            projekt_id = (kapitel or {}).get("projektId")

            # Step 1: Generate/fetch summaries for context Kapitels (in parallel)
            context_ids = [str(cid) for cid in (context_kapitel_ids or []) if str(cid) != str(kapitel_id)]
            logger.info(f"Generating summaries for {len(context_ids)} context Kapitels")

            summaries: dict[str, str] = {}
            valid_context_ids: list[str] = []

            if context_ids:
                summary_tasks = [
                    self.get_or_create_summary(
                        user_id,
                        kapitel_id,
                        run_id,
                        ctx_id,
                        model,
                        api_key,
                        key_source,
                        user_action_id,
                    )
                    for ctx_id in context_ids
                ]
                summaries_list = await asyncio.gather(*summary_tasks, return_exceptions=True)

                for ctx_id, summary_result in zip(context_ids, summaries_list):
                    if isinstance(summary_result, Exception):
                        logger.error(f"Failed to get summary for Kapitel {ctx_id}: {summary_result}")
                    else:
                        summaries[str(ctx_id)] = str(summary_result or "")
                        valid_context_ids.append(str(ctx_id))

            # Step 2: Build full Gliederung for the entire project (summaries only where available)
            logger.info("Building Gliederung")

            all_kapitels: list[dict] = []
            if (projekt_id or "").strip():
                all_kapitels = await firebase_service.list_kapitel_metadata_for_project(user_id, projekt_id)

            if not all_kapitels:
                fallback_ids = list(dict.fromkeys([kapitel_id] + valid_context_ids))
                for kid in fallback_ids:
                    metadata = await firebase_service.get_kapitel_metadata(user_id, kid)
                    if metadata:
                        all_kapitels.append(metadata)

            all_kapitels.sort(key=lambda k: self._nummer_sort_key(k.get("nummer", "")))
            gliederung = await self.build_gliederung(user_id, kapitel_id, all_kapitels, summaries)

            # Step 3: Shorten the target text
            logger.info("Shortening target Kapitel text")

            active_template_id = await firebase_service.get_active_prompt_id(user_id, "shorten")
            template_instructions = await prompt_service.get_instructions_for_template(
                user_id, "shorten", active_template_id
            )
            template_system_prompt = await prompt_service.get_system_prompt_for_template(
                stage="shorten",
                template_id=active_template_id,
            )

            payload = {
                "KAPITEL_TITEL": ueberschrift,
                "KAPITEL_BESCHREIBUNG": thema,
                "GLIEDERUNG_SUMMARY": gliederung,
                "KAPITELTEXT": target_text,
            }
            rendered = prompt_service.render(template_instructions, payload)
            uses_inline_inputs = ("{GLIEDERUNG_SUMMARY}" in template_instructions) and (
                "{KAPITELTEXT}" in template_instructions
            )

            prompt_body = rendered
            if not uses_inline_inputs:
                prompt_body = f"""{rendered}

### Gliederung:
{gliederung}

### Text zum Kürzen:
{target_text}"""

            await get_credits_service(firebase_service).assert_not_negative_balance(user_id)

            shortened_content, usage = await self.shorten_and_deduplicate(
                prompt_body,
                model,
                api_key=api_key,
                system_prompt=template_system_prompt,
            )

            input_tokens = int(usage.get("prompt_tokens", 0))
            cached_input_tokens = int(usage.get("prompt_tokens_details", {}).get("cached_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
            total_tokens = input_tokens + output_tokens

            cost_service = get_cost_service(firebase_service)
            usage_obj = TokenUsage.from_any(input_tokens, cached_input_tokens, output_tokens)
            cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(
                model=model,
                usage=usage_obj,
            )

            projekt_snapshot = None
            if projekt_id:
                project = await firebase_service.get_project(user_id, projekt_id)
                if project:
                    projekt_snapshot = {
                        "id": projekt_id,
                        "name": project.get("name"),
                        "archived": bool(project.get("archived", False)),
                    }

            kapitel_snapshot = (
                {
                    "id": kapitel_id,
                    "nummer": (kapitel or {}).get("nummer", "?"),
                    "title": (kapitel or {}).get("title", "Untitled"),
                }
                if kapitel
                else None
            )

            run_snapshot = {
                "id": run_id,
                "index": (run_data or {}).get("index"),
            }

            await cost_service.log_operation(
                operation_type="shorten",
                user_id=user_id,
                user_action_id=user_action_id,
                operation_details={
                    "usedKapitelIds": valid_context_ids,
                    "summaryCount": len(summaries),
                },
                model=model,
                usage=usage_obj,
                cost_breakdown=cost_breakdown,
                matched_model_key=matched_model,
                pricing=pricing,
                key_source=key_source,
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                projekt_snapshot=projekt_snapshot,
                kapitel_snapshot=kapitel_snapshot,
                run_snapshot=run_snapshot,
            )

            cost = float(cost_breakdown.total_cost_usd)

            # Count words
            original_length = len(target_text.split())
            shortened_length = len(shortened_content.split())

            # Step 4: Save the shortened result
            logger.info("Saving shortened result")

            shortened_data = {
                "content": shortened_content,
                "originalLength": original_length,
                "shortenedLength": shortened_length,
                "compressionRatio": shortened_length / original_length if original_length > 0 else 0,
                "usedKapitelIds": valid_context_ids,
                "model": model,
                "usage": {
                    "inputTokens": input_tokens,
                    "cachedInputTokens": cached_input_tokens,
                    "outputTokens": output_tokens,
                    "reasoningTokens": 0,
                    "totalTokens": total_tokens,
                },
                "costUsd": float(cost),
                "keySource": key_source,
            }

            await firebase_service.save_shortened_result(
                user_id, kapitel_id, run_id, shortened_data
            )

            logger.info(
                f"Shorten process complete for Kapitel {kapitel_id}: "
                f"{original_length} -> {shortened_length} words ({shortened_length/original_length*100:.1f}%), "
                f"cost: ${cost:.4f}"
            )

        except Exception as e:
            logger.error(
                f"Error in shorten process for Kapitel {kapitel_id}, run {run_id}: {e}",
                exc_info=True
            )
            raise

    async def build_gliederung_with_descriptions(
        self,
        user_id: str,
        target_kapitel_id: str,
        context_kapitels: List[dict],
        summaries: Dict[str, str],
    ) -> str:
        """
        Build the Gliederung with chapter descriptions.

        Format:
        ### Zusammenfassung Kapitel 1
        1.1 Title
        Summary of 1.1...

        1.2 Title
        Summary of 1.2...

        ### Zusammenfassung Kapitel 2
        ...

        Args:
            context_kapitels: List of Kapitel dicts with 'id', 'nummer', 'title'
            summaries: Dict mapping kapitel_id to summary_content

        Returns:
            str: Formatted Gliederung text
        """
        lines = []

        # Group kapitels by their main chapter number (e.g., "2" from "2.1.3")
        from collections import defaultdict
        chapters = defaultdict(list)

        for kapitel in context_kapitels:
            nummer = kapitel.get('nummer', '?')
            # Extract main chapter (first digit/number before first dot)
            main_chapter = nummer.split('.')[0] if '.' in nummer else nummer
            chapters[main_chapter].append(kapitel)

        # Sort main chapters
        sorted_chapters = sorted(chapters.keys(), key=lambda x: float(x) if x.replace('.','').isdigit() else 999)

        for main_chapter in sorted_chapters:
            # Add chapter header
            lines.append(f"### Zusammenfassung Kapitel {main_chapter}")
            lines.append("")

            # Add all kapitels in this chapter
            for kapitel in chapters[main_chapter]:
                kapitel_id = kapitel['id']
                nummer = kapitel.get('nummer', '?')
                title = kapitel.get('title', 'Untitled')

                # Add the Kapitel header with description
                lines.append(f"{nummer} {title}")

                # Add the summary if available
                if kapitel_id in summaries:
                    lines.append(summaries[kapitel_id])
                else:
                    lines.append("[Keine Zusammenfassung verfügbar]")

                lines.append("")  # Empty line between kapitels

            lines.append("")  # Extra empty line between chapters

        return "\n".join(lines)

    async def improve_reading_flow(
        self,
        aufgabenstellung: str,
        gliederung: str,
        kapitel_nummer: str,
        target_text: str,
        model: str,
        api_key: Optional[str] = None,
        instructions: Optional[str] = None,
        system_prompt: Optional[str] = None,
        debug_prompt_dump_path: Optional[str] = None,
    ) -> Tuple[str, dict]:
        """
        Improve reading flow using OpenAI.

        Returns:
            tuple: (lesefluss_content, usage_dict)
        """
        prompt = f"""### Aufgabe
Ich schreibe gerade meine Wissenschaftlichen Arbeit.
Momentan sind die Texte aus den verschiedenen Unterkapiteln noch sehr "alleinstehend" was ich meine ist das in den einzelnen Unterkapitel nicht auf die Folgenden oder kommenden Kapitel eingegangen wird und der Text somit noch sehr gestückelt und keine Gesamtheit ist. Auch kommen Informationen doppelt vor oder das Thema wird unterschiedlich behandelt in verschiedenen Unterkapiteln.
Für einen besseren Kontext für dich ist hier die Aufgabenstellung für die gesamte Arbeit:

AUFGABENSTELLUNG:
{aufgabenstellung}
AUFGABENSTELLUNG ENDE

Ich werde dir außerdem eine zusammengefasste Version der ganzen Arbeit geben. Zu jedem Unterkapitel gibt es einen am Anfang kleinen Text der beschreibt was in diesem Unterkapitel für Informationen behandelt werden. Allerdings sind die Texte zusammengefasst, da die ganze Arbeit zu lang wäre. Berücksichtige diese Information wenn die auf ein Kapitel verweist. Dies ist damit du einen besseren Kontext für die ganze Arbeit hast. Du kannst auch auf Informationen die hier bearbeitet wurden verweisen.
Ich will von dir das du einen fließenden Text aus dem ganzen machst, dass in dem Text an dem du gerade Arbeitest auf bereits behandelte Informationen verwiesen werden kann, wenn das Sinn macht, oder das darauf verwiesen wird, das etwas noch tiefer bearbeitet werden wird in einem kommenden Kapitel. Wenn du auf ein anderes Kapitel verweißt, dann schreibe nicht „wie in 2.2 beschrieben…" sondern „wie in Kapitel 2.2 beschrieben …" also schreibe dazu das du auf das Kapitel xy verweist.
Nutze die letzten Absätze deines Textes dazu, eine subtile Überleitung in das nächste Kapitel einzuweben. Schreibe nicht einfach am ende einen kurzen Absatz in dem du überleitest. Der Lesefluss soll nicht unterbrochen werden. Schreibe auch nicht "dies leitet über". Gebe dir mühe bei der Überleitung da dies den Text Charakter verleiht. Habe Spaß mit der Findung. Nutze nur die Informationen die in den Texten gegeben sind, ergänze nichts dazu, das nicht in den Texten steht.. Übernehme außerdem die angegebenen Quellen (mit Seitenzahlen, wenn Seitenzahlen in der Quelle vorhanden sind) in deinen Text. Gehe sicher, dass keine Informationen weggelassen werden. Erfinde aber auch keine zusätzlichen Kapitel oder Informationen hinzu. Was du aber machen kannst ist zusätzliche Informationen so zu nutzen das neue Schlüsse gezogen werden, gehe aber sicher diese dann immer so zu formulieren das klar wird das es sich hier um dein Gedankengut und nicht um Wissenschaftlich bewiesenes geht. Formuliere den Text ohne das du ; verwendest, außer zwischen zwei Quellen.


{gliederung}

### Kapitel {kapitel_nummer} (TEXT AN DEM DU ARBEITEN SOLLST)
{target_text}
"""
        if instructions:
            prompt = f"""{instructions}

### Gliederung:
{gliederung}

### Kapitel {kapitel_nummer} (TEXT AN DEM DU ARBEITEN SOLLST)
{target_text}"""

        result_text, usage = await openai_service.improve_reading_flow(
            prompt,
            model,
            api_key=api_key,
            system_prompt=system_prompt,
            debug_prompt_dump_path=debug_prompt_dump_path,
        )

        return (result_text or "").strip(), usage

    async def process_lesefluss_request(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        context_kapitel_ids: List[str],
        aufgabenstellung: str,
        model: str,
        api_key: Optional[str] = None,
        key_source: str = "backend"
    ) -> None:
        """
        Main orchestration method for improving reading flow (Lese Fluss).

        This method:
        1. Gets the shortened text for the target Kapitel
        2. Gets summaries for all context Kapitels (with caching)
        3. Builds the Gliederung (with summaries)
        4. Calls OpenAI with special prompt for flow improvement
        5. Saves the result
        """
        try:
            user_action_id = str(uuid.uuid4())
            logger.info(
                f"Starting lesefluss process for Kapitel {kapitel_id}, run {run_id}, "
                f"with {len(context_kapitel_ids)} context Kapitels"
            )

            # Step 1: Get the target Kapitel's SHORTENED text from the specific run
            shortened = await firebase_service.get_shortened_result(user_id, kapitel_id, run_id)
            if not shortened or not (shortened.get("content") or "").strip():
                raise ValueError(
                    f"No shortened text found for Kapitel {kapitel_id} in run {run_id}. "
                    f"Please shorten the text first before improving reading flow."
                )

            target_text = shortened["content"]

            # Get the target Kapitel's metadata
            run_data = await firebase_service.get_kapitel_run(user_id, kapitel_id, run_id)
            if not run_data:
                raise ValueError(f"Run {run_id} not found for Kapitel {kapitel_id}")

            # Enforce run-level model for all actions tied to this run.
            run_model = (run_data.get("model") or "").strip()
            if run_model:
                if model and model != run_model:
                    logger.info(
                        f"Overriding requested model '{model}' with run model '{run_model}' "
                        f"(Kapitel {kapitel_id}, run {run_id})"
                    )
                model = run_model
            else:
                logger.warning(
                    f"Run {run_id} for Kapitel {kapitel_id} has no model; falling back to requested model '{model}'"
                )

            kapitel = await firebase_service.get_kapitel(user_id, kapitel_id)
            projekt_id = (kapitel or {}).get("projektId")

            kapitel_nummer = (kapitel or {}).get("nummer") or run_data.get("nummer") or "?"

            # Step 2: Generate/fetch summaries for context Kapitels (in parallel)
            context_ids = [str(cid) for cid in (context_kapitel_ids or []) if str(cid) != str(kapitel_id)]
            logger.info(f"Generating summaries for {len(context_ids)} context Kapitels")

            summaries: dict[str, str] = {}
            valid_context_ids: list[str] = []

            if context_ids:
                summary_tasks = [
                    self.get_or_create_summary(
                        user_id,
                        kapitel_id,
                        run_id,
                        ctx_id,
                        model,
                        api_key,
                        key_source,
                        user_action_id,
                    )
                    for ctx_id in context_ids
                ]
                summaries_list = await asyncio.gather(*summary_tasks, return_exceptions=True)

                for ctx_id, summary_result in zip(context_ids, summaries_list):
                    if isinstance(summary_result, Exception):
                        logger.error(f"Failed to get summary for Kapitel {ctx_id}: {summary_result}")
                    else:
                        summaries[str(ctx_id)] = str(summary_result or "")
                        valid_context_ids.append(str(ctx_id))

            if not summaries:
                raise ValueError("No valid summaries could be generated for context Kapitels")

            # Step 3: Build full Gliederung for the entire project (summaries only where available)
            logger.info("Building Gliederung")

            all_kapitels: list[dict] = []
            if (projekt_id or "").strip():
                all_kapitels = await firebase_service.list_kapitel_metadata_for_project(user_id, projekt_id)

            if not all_kapitels:
                fallback_ids = list(dict.fromkeys([kapitel_id] + valid_context_ids))
                for kid in fallback_ids:
                    metadata = await firebase_service.get_kapitel_metadata(user_id, kid)
                    if metadata:
                        all_kapitels.append(metadata)

            all_kapitels.sort(key=lambda k: self._nummer_sort_key(k.get("nummer", "")))

            next_kapitel_nummer = ""
            uebernaechstes_kapitel_nummer = ""
            for idx, k in enumerate(all_kapitels):
                if str(k.get("id")) == str(kapitel_id):
                    kapitel_nummer = str(k.get("nummer") or kapitel_nummer or "?")
                    if idx + 1 < len(all_kapitels):
                        next_kapitel_nummer = str(all_kapitels[idx + 1].get("nummer") or "")
                    if idx + 2 < len(all_kapitels):
                        uebernaechstes_kapitel_nummer = str(all_kapitels[idx + 2].get("nummer") or "")
                    break

            gliederung = await self.build_gliederung(user_id, kapitel_id, all_kapitels, summaries)

            # Step 4: Call OpenAI to improve reading flow
            logger.info("Improving reading flow for target Kapitel text")

            active_template_id = await firebase_service.get_active_prompt_id(user_id, "lesefluss")
            template_instructions = await prompt_service.get_instructions_for_template(
                user_id, "lesefluss", active_template_id
            )
            template_system_prompt = await prompt_service.get_system_prompt_for_template(
                stage="lesefluss",
                template_id=active_template_id,
            )

            payload = {
                "AUFGABENSTELLUNG": aufgabenstellung,
                "GLIEDERUNG_SUMMARY": gliederung,
                "KAPITELTEXT": target_text,
                "AKTUELLES_KAPITEL_NUMMER": str(kapitel_nummer),
                "NAECHSTES_KAPITEL_NUMMER": next_kapitel_nummer,
                "UEBERNAECHSTES_KAPITEL_NUMMER": uebernaechstes_kapitel_nummer,
            }

            rendered = prompt_service.render(template_instructions, payload)
            uses_inline_inputs = (
                ("{GLIEDERUNG_SUMMARY}" in template_instructions and "{KAPITELTEXT}" in template_instructions)
            )

            prompt_body = rendered
            if not uses_inline_inputs:
                prompt_body = f"""{rendered}

### Gliederung:
{gliederung}

### Kapitel {kapitel_nummer} (TEXT AN DEM DU ARBEITEN SOLLST)
{target_text}"""

            await get_credits_service(firebase_service).assert_not_negative_balance(user_id)

            lesefluss_content, usage = await openai_service.improve_reading_flow(
                prompt_body,
                model,
                api_key=api_key,
                system_prompt=template_system_prompt,
            )

            input_tokens = int(usage.get("prompt_tokens", 0))
            cached_input_tokens = int(usage.get("prompt_tokens_details", {}).get("cached_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
            total_tokens = input_tokens + output_tokens

            cost_service = get_cost_service(firebase_service)
            usage_obj = TokenUsage.from_any(input_tokens, cached_input_tokens, output_tokens)
            cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(
                model=model,
                usage=usage_obj,
            )

            projekt_snapshot = None
            if projekt_id:
                project = await firebase_service.get_project(user_id, projekt_id)
                if project:
                    projekt_snapshot = {
                        "id": projekt_id,
                        "name": project.get("name"),
                        "archived": bool(project.get("archived", False)),
                    }

            kapitel_snapshot = (
                {
                    "id": kapitel_id,
                    "nummer": (kapitel or {}).get("nummer", "?"),
                    "title": (kapitel or {}).get("title", "Untitled"),
                }
                if kapitel
                else None
            )

            run_snapshot = {
                "id": run_id,
                "index": (run_data or {}).get("index"),
            }

            await cost_service.log_operation(
                operation_type="lesefluss",
                user_id=user_id,
                user_action_id=user_action_id,
                operation_details={
                    "usedKapitelIds": valid_context_ids,
                    "summaryCount": len(summaries),
                },
                model=model,
                usage=usage_obj,
                cost_breakdown=cost_breakdown,
                matched_model_key=matched_model,
                pricing=pricing,
                key_source=key_source,
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                projekt_snapshot=projekt_snapshot,
                kapitel_snapshot=kapitel_snapshot,
                run_snapshot=run_snapshot,
            )

            cost = float(cost_breakdown.total_cost_usd)

            # Count words
            original_length = len(target_text.split())
            lesefluss_length = len(lesefluss_content.split())

            # Step 5: Save the lesefluss result
            logger.info("Saving lesefluss result")

            lesefluss_data = {
                "content": lesefluss_content,
                "aufgabenstellung": aufgabenstellung,
                "originalLength": original_length,
                "leseflussLength": lesefluss_length,
                "usedKapitelIds": valid_context_ids,
                "model": model,
                "usage": {
                    "inputTokens": input_tokens,
                    "cachedInputTokens": cached_input_tokens,
                    "outputTokens": output_tokens,
                    "reasoningTokens": 0,
                    "totalTokens": total_tokens,
                },
                "costUsd": float(cost),
                "keySource": key_source,
            }

            await firebase_service.save_lesefluss_result(
                user_id, kapitel_id, run_id, lesefluss_data
            )

            logger.info(
                f"Lesefluss process complete for Kapitel {kapitel_id}: "
                f"{original_length} -> {lesefluss_length} words, "
                f"cost: ${cost:.4f}"
            )

        except Exception as e:
            logger.error(
                f"Error in lesefluss process for Kapitel {kapitel_id}, run {run_id}: {e}",
                exc_info=True
            )
            raise


# Create singleton instance
shorten_service = ShortenService()
