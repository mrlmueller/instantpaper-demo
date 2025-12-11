from services.firebase_service import firebase_service
from services.openai_service import openai_service
from services.quelle_service import calculate_cost
import logging
import asyncio
from datetime import datetime
import os
import json
import services.openai_service as openai_module

logger = logging.getLogger(__name__)

# TEMPORARY: Debug prompt saving
# Use project-root-relative path so files land inside the repo regardless of host OS
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEBUG_PROMPT_DIR = os.path.join(PROJECT_ROOT, "debug_prompts")
os.makedirs(DEBUG_PROMPT_DIR, exist_ok=True)


class ShortenService:
    """Service for shortening and deduplicating Kapitel texts"""

    def __init__(self):
        pass

    async def get_latest_text_for_kapitel(
        self,
        user_id: str,
        kapitel_id: str,
    ) -> tuple[str, str, str]:
        """
        Get the latest text for a Kapitel (shortened if exists, else combined).

        Returns:
            tuple: (text_content, run_id, text_type) where text_type is 'shortened' or 'combined'

        Raises:
            ValueError: If no text is found
        """
        logger.info(f"Getting latest text for Kapitel {kapitel_id}")

        # Get all runs for this Kapitel
        runs = await firebase_service.get_kapitel_runs(user_id, kapitel_id)

        if not runs:
            raise ValueError(f"No runs found for Kapitel {kapitel_id}")

        # Sort by createdAt (most recent first)
        sorted_runs = sorted(runs, key=lambda r: r.get('createdAt', ''), reverse=True)

        # Try to find shortened text first, then combined
        for run in sorted_runs:
            run_id = run['id']

            # Check for shortened text
            shortened = await firebase_service.get_shortened_result(user_id, kapitel_id, run_id)
            if shortened and shortened.get('shortened_content'):
                logger.info(f"Found shortened text for Kapitel {kapitel_id} in run {run_id}")
                return (shortened['shortened_content'], run_id, 'shortened')

            # Check for combined text
            combined = await firebase_service.get_combined_result(user_id, kapitel_id, run_id)
            if combined and combined.get('combined_content'):
                logger.info(f"Found combined text for Kapitel {kapitel_id} in run {run_id}")
                return (combined['combined_content'], run_id, 'combined')

        raise ValueError(f"No text found for Kapitel {kapitel_id}")

    async def is_summary_valid(
        self,
        summary: dict,
        current_run_id: str,
        current_text_type: str
    ) -> bool:
        """
        Check if a cached summary is still valid.

        A summary is valid if:
        1. It was created from the same run
        2. It was created from the same text type (combined vs shortened)
        """
        source_run_id = summary.get('source_run_id')
        source_type = summary.get('source_type')

        is_valid = (source_run_id == current_run_id and source_type == current_text_type)

        logger.info(
            f"Summary validation: source_run_id={source_run_id}, source_type={source_type}, "
            f"current_run_id={current_run_id}, current_type={current_text_type} -> {is_valid}"
        )

        return is_valid

    async def get_or_create_summary(
        self,
        user_id: str,
        target_kapitel_id: str,
        target_run_id: str,
        source_kapitel_id: str,
        model: str,
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
                return cached_summary['summary_content']
            else:
                logger.info(f"Cached summary invalid for Kapitel {source_kapitel_id}, regenerating")

        # Generate new summary
        logger.info(f"Generating new summary for Kapitel {source_kapitel_id}")
        summary_content, usage = await self.summarize_text(source_text, model, source_kapitel_id)

        # Calculate cost
        cost = calculate_cost(
            model,
            usage.get('prompt_tokens', 0),
            usage.get('prompt_tokens_details', {}).get('cached_tokens', 0),
            usage.get('completion_tokens', 0)
        )

        # Convert to cents
        cost_cents = int(cost * 100)

        # Count words
        original_length = len(source_text.split())
        summary_length = len(summary_content.split())

        # Save the summary
        summary_data = {
            'summary_content': summary_content,
            'source_kapitel_id': source_kapitel_id,
            'source_run_id': source_run_id,
            'source_type': source_type,
            'original_length': original_length,
            'summary_length': summary_length,
            'model': model,
            'cost': cost_cents,
            'tokens_used': {
                'input': usage.get('prompt_tokens', 0),
                'output': usage.get('completion_tokens', 0),
            },
            'created_at': datetime.utcnow().isoformat() + 'Z',
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

    async def summarize_text(self, text: str, model: str, source_kapitel_id: str = None) -> tuple[str, dict]:
        """
        Summarize text to ~30% of original using OpenAI.

        Returns:
            tuple: (summary_content, usage_dict)
        """
        prompt = f"""### Aufgabe:
Fasse folgenden Text zusammen, sodass er auf ungefähr 30% Wörter vom Original Text kommt. Ziel dieser Zusammenfassung ist es, die Rhetorik und nebensächliche Informationen wegzulassen, aber die grundlegenden Informationen beizubehalten. Schreibe lieber Sätze die sich nicht flüssig lesen lassen, also ohne viele Stopwörter sind und integriere dafür aber mehr Information. Das Ziel ist einen Text der so kurz wie möglich aber auch so viele Informationen wie möglich hat. Quellen können weggelassen werden.

### Text:
{text}"""

        # TEMPORARY: Save prompt to file for debugging
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
            kapitel_suffix = f"_kapitel_{source_kapitel_id[:8]}" if source_kapitel_id else ""
            prompt_file = os.path.join(DEBUG_PROMPT_DIR, f"summarize_{timestamp}{kapitel_suffix}.md")
            with open(prompt_file, 'w', encoding='utf-8') as f:
                messages = [
                    {"role": "system", "content": openai_module.SUMMARIZE_SYSTEM_MESSAGE},
                    {"role": "user", "content": prompt},
                ]
                json.dump(messages, f, ensure_ascii=False, indent=2)
            logger.info(f"DEBUG: Saved summarization prompt to {prompt_file}")
        except Exception as e:
            logger.error(f"DEBUG: Failed to save prompt file: {e}")

        return await openai_service.summarize_kapitel(prompt, model)

    async def build_gliederung(
        self,
        user_id: str,
        target_kapitel_id: str,
        context_kapitels: list[dict],
        summaries: dict[str, str],
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
            lines.append(f"{nummer}. {title}")

            # Add the summary if available
            if kapitel_id in summaries:
                lines.append(summaries[kapitel_id])
            else:
                lines.append("[Keine Zusammenfassung verfügbar]")

            lines.append("")  # Empty line between Kapitels

        return "\n".join(lines)

    async def shorten_and_deduplicate(
        self,
        ueberschrift: str,
        thema: str,
        gliederung: str,
        target_text: str,
        model: str,
        target_kapitel_id: str = None,
        context_kapitel_ids: list = None,
    ) -> tuple[str, dict, dict]:
        """
        Shorten and deduplicate text using OpenAI.

        Returns:
            tuple: (shortened_content, usage_dict, explanation_dict)
        """
        prompt = f"""### Aufgabe:
Ich schreibe gerade eine Wissenschaftliche Arbeit. Der folgende Text ist bereits gut, so wie er ist, allerding ist er noch zu lang. Aber damit du optimal den Text kürzen kannst, also das du den Fokus auf die richtigen Fakten und Themen legen kannst werde ich dir die Überschrift „{ueberschrift}" und auch das Thema des Textes geben „{thema}". Zusätzlich werde ich dir Folgend einen Teil meiner Gliederung geben zusammen mit einer zusammengefassten Version der Texte von den anderen Kapitel und Unterpunkten der Kapitel. All dies gebe ich dir damit du perfekt entscheiden kannst auf was der Fokus gelegt werden sollte in der Arbeit. Konkret ist deine Aufgabe den Text auf die hälft oder noch etwas weniger zu kürzen, aber dabei alle wichtigen Informationen bei zu behalten. Behalte auch sämtliche Quellen an den richtigen Stellen bei außer, wenn du eine Information zu einer Quelle komplett eliminierst. Du sollst nur die gegebenen Informationen nutzen, und keine Informationen aus deinem eigenen wissen mit einbeziezen! Schreibe keine Zusammenfassung am Ende, da dies nur ein Teil eines längeren Textes ist. Habe Spaß mit der Findung deines Textes. Schreibe ohne "Wir/Ich haben herausgefunden". Schreibe aber dennoch das es Spaß macht den Text zu lesen, also dass es kein zu trockener Text wird, aber behalte dennoch die Wissenschaftliche Schreibweise bei. Wenn du Argumente beschreibst, gehe sicher immer eine Quelle zu integrieren. Formuliere den Text ohne das du ; verwendest, außer zwischen zwei Quellen.

WICHTIG: Antworte mit einem JSON-Objekt wie im System-Prompt beschrieben. Gebe eine kurze Erklärung deiner Entscheidungen im explanation-Feld und den gekürzten Text im shortened_text-Feld.

### Gliederung:
{gliederung}

### Text zum Kürzen:
{target_text}"""

        # TEMPORARY: Save prompt to file for debugging
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
            kapitel_suffix = f"_kapitel_{target_kapitel_id[:8]}" if target_kapitel_id else ""
            prompt_file = os.path.join(DEBUG_PROMPT_DIR, f"shorten_{timestamp}{kapitel_suffix}.md")
            with open(prompt_file, 'w', encoding='utf-8') as f:
                messages = [
                    {"role": "system", "content": openai_module.SHORTEN_SYSTEM_MESSAGE},
                    {"role": "user", "content": prompt},
                ]
                json.dump(messages, f, ensure_ascii=False, indent=2)
            logger.info(f"DEBUG: Saved shorten prompt to {prompt_file}")
        except Exception as e:
            logger.error(f"DEBUG: Failed to save prompt file: {e}")

        return await openai_service.shorten_and_deduplicate(prompt, model)

    async def process_shorten_request(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        context_kapitel_ids: list[str],
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
            logger.info(
                f"Starting shorten process for Kapitel {kapitel_id}, run {run_id}, "
                f"with {len(context_kapitel_ids)} context Kapitels"
            )

            # Get the target Kapitel's combined text from the specific run
            combined = await firebase_service.get_combined_result(user_id, kapitel_id, run_id)
            if not combined or not combined.get('combined_content'):
                raise ValueError(
                    f"No combined text found for Kapitel {kapitel_id} in run {run_id}. "
                    f"Please ensure the Kapitel has been processed first."
                )

            target_text = combined['combined_content']
            target_run_id = run_id
            target_type = 'combined'

            # Get the target Kapitel's run metadata for ueberschrift and thema
            run_data = await firebase_service.get_kapitel_run(user_id, kapitel_id, run_id)
            if not run_data:
                raise ValueError(f"Run {run_id} not found for Kapitel {kapitel_id}")

            ueberschrift = run_data.get('ueberschrift', 'Untitled')
            thema = run_data.get('thema', '')

            # Step 1: Generate/fetch summaries for context Kapitels (in parallel)
            logger.info(f"Generating summaries for {len(context_kapitel_ids)} context Kapitels")

            summary_tasks = [
                self.get_or_create_summary(user_id, kapitel_id, run_id, ctx_id, model)
                for ctx_id in context_kapitel_ids
            ]

            summaries_list = await asyncio.gather(*summary_tasks, return_exceptions=True)

            # Build summaries dict, filtering out errors
            summaries = {}
            valid_context_ids = []
            for ctx_id, summary_result in zip(context_kapitel_ids, summaries_list):
                if isinstance(summary_result, Exception):
                    logger.error(f"Failed to get summary for Kapitel {ctx_id}: {summary_result}")
                else:
                    summaries[ctx_id] = summary_result
                    valid_context_ids.append(ctx_id)

            if not summaries:
                raise ValueError("No valid summaries could be generated for context Kapitels")

            # Step 2: Get metadata for context Kapitels to build Gliederung
            logger.info("Building Gliederung")

            context_kapitels = []
            for ctx_id in valid_context_ids:
                metadata = await firebase_service.get_kapitel_metadata(user_id, ctx_id)
                if metadata:
                    context_kapitels.append(metadata)

            # Sort by nummer for proper ordering
            context_kapitels.sort(key=lambda k: k.get('nummer', ''))

            gliederung = await self.build_gliederung(
                user_id, kapitel_id, context_kapitels, summaries
            )

            # Step 3: Shorten the target text
            logger.info("Shortening target Kapitel text")

            shortened_content, usage, explanation = await self.shorten_and_deduplicate(
                ueberschrift, thema, gliederung, target_text, model,
                target_kapitel_id=kapitel_id,
                context_kapitel_ids=valid_context_ids
            )

            # Calculate cost
            cost = calculate_cost(
                model,
                usage.get('prompt_tokens', 0),
                usage.get('prompt_tokens_details', {}).get('cached_tokens', 0),
                usage.get('completion_tokens', 0)
            )

            # Convert to cents
            cost_cents = int(cost * 100)

            # Count words
            original_length = len(target_text.split())
            shortened_length = len(shortened_content.split())

            # Step 4: Save the shortened result
            logger.info("Saving shortened result")

            shortened_data = {
                'shortened_content': shortened_content,
                'explanation': {
                    'length_decision': explanation.get('length_decision', ''),
                    'omitted_topics': explanation.get('omitted_topics', []),
                    'preserved_focus': explanation.get('preserved_focus', []),
                    'compression_notes': explanation.get('compression_notes', '')
                },
                'original_length': original_length,
                'shortened_length': shortened_length,
                'compression_ratio': shortened_length / original_length if original_length > 0 else 0,
                'used_kapitel_ids': valid_context_ids,
                'model': model,
                'cost': cost_cents,
                'tokens_used': {
                    'input': usage.get('prompt_tokens', 0),
                    'cached_input': usage.get('prompt_tokens_details', {}).get('cached_tokens', 0),
                    'output': usage.get('completion_tokens', 0),
                },
                'created_at': datetime.utcnow().isoformat() + 'Z',
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


# Create singleton instance
shorten_service = ShortenService()
