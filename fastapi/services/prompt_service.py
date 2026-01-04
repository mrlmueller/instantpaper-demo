from services.firebase_service import firebase_service
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


PROCESS_QUELLE_DEFAULT_SYSTEM_PROMPT = (
    "<Prompt entfernt>"
    "You can analyze both text and images provided. "
    "Think step-by-step to ensure correctness. "
    "If the Quelle does NOT contain any useful information for the request, respond with the single token 'NO_CONTENT' only. "
    "Otherwise, return only the final answer without any extra commentary."
)

PROCESS_QUELLE_DEFAULT_V2_SYSTEM_PROMPT = """<Prompt entfernt>"""

PROCESS_QUELLE_DEFAULT_V2_INSTRUCTIONS = """<Prompt entfernt>";" verwenden. Ausnahme: ausschließlich innerhalb eines einzigen Klammerausdrucks, um zwei Quellen zu trennen, z. B. (Autor, Jahr; Autor, Jahr).
- Vermeide interne Verweise aus der Quelle wie „Abschn. X“, „Kapitel Y“, „vgl. Abschn. …“. Wenn der Inhalt wichtig ist, formuliere ihn ohne solche Verweise.
- Abbildungen müssen nicht referenziert werden. Wenn Bildinformationen im Input enthalten sind, integriere nur deren Inhalt sachlich in den Text, ohne „Abbildung …“ zu schreiben. Außer du hast eine Referenz für die Bildinformationen in dem Text.

[ZITIERREGELN (APA)]
- Teilquellen, die im Quelltext bereits stehen (z. B. (Name, Jahr)), übernimm an der passenden fachlichen Aussage.
- Wenn eine fachliche Aussage klar aus dem bereitgestellten Input stammt, aber im Input an dieser Stelle keine Teilquelle genannt ist, nutze als Beleg die Quelle dir für die Quelle gegeben wurde.
- Keine Quellen erfinden. Keine Autor:innen/Jahre raten. Keine Zitate für Inhalte, die nicht im Input stehen.
- Grundlegende Informationen dürfen ohne Zitat verwendet werden (sofern sie im Input stehen). Fachliche Behauptungen aus dem Quelltext selbst weiterhin zitieren.

[ANTI-PLAGIAT – MUSS]
- Keine wörtlichen Übernahmen: übernimm keine längeren Wortfolgen oder charakteristischen Formulierungen aus der Quelle.
- Schreibe nicht „satzweise entlang“ der Quelle. Ändere die Reihenfolge der Informationen sinnvoll, bündele ähnliche Punkte, abstrahiere Details, und formuliere neue Satzstrukturen.
- Nutze eigene Satzlogik: erst den inhaltlichen Kern erfassen, dann komplett neu formulieren (anderes Satzgerüst, andere Reihenfolge, andere Perspektive/Grammatik).
- Wenn ein Satz „zu nah“ klingt, schreibe ihn neu, bis er klar eigenständig wirkt.
- Wichtig ist, dass Informationen, die aus der Quelle übernommen werden, so umgeschrieben werden sollen, dass der obige Text nicht mehr zu erkennen ist - das Ergebnis also einzigartig ist

[STILLE PRÜFUNG VOR AUSGABE]
Prüfe intern, ohne es zu schreiben:
1) Der Absatz behandelt wirklich nur {KAPITEL_BESCHREIBUNG} (Randinfos sind ok, solange thematisch anschlussfähig).
2) Keine erfundenen Fakten.
3) Jede fachliche Behauptung aus dem Quelltext hat eine passende APA-Zitation.
4) Keine internen Abschnitts-/Kapitelverweise übernommen.
5) Text ist eindeutig neu formuliert und einzigartig.

[GRUNDLEGENDE INFORMATIONEN - OPTIONAL]
{OPTIONAL_GRUNDLEGENDE_INFOS}

{QUELLE_ZITAT}

Quelltext:
{QUELLTEXT}
"""


COMBINE_DEFAULT_SYSTEM_PROMPT = "<Prompt entfernt>"

COMBINE_DEFAULT_V2_SYSTEM_PROMPT = """<Prompt entfernt>"""

COMBINE_DEFAULT_V2_INSTRUCTIONS = """[AUFGABE]
Füge die folgenden Entwürfe zu einem kohärenten wissenschaftlichen Fließtext zusammen. Der Fließtext ist Teil einer großeren Arbeit. Das Kapitel das du schreiben sollst, 
hat den titel den du unten siehst und behandelt das Thema das du ebenfalls unten siehst. Thema ist einfach nur ein kleiner Text der beschreibt um was es in dem Kapitel genau gehen soll.

Titel (nur Kontext, NICHT ausgeben): {KAPITEL_TITEL}
Thema: {KAPITEL_BESCHREIBUNG}

Anforderungen:
- Integriere alle relevanten Informationen aus den Entwürfen. Entferne Dopplungen konsequent.
- Schreibe nicht „Thema A, Thema B, Thema C“ hintereinander, sondern baue eine sinnvolle argumentative Reihenfolge mit klaren Übergängen.
- Du darfst Informationen synthetisieren und logisch verbinden, aber keine neuen Fakten hinzufügen.
- Jede fachliche Aussage muss mit einer im Input vorhandenen Quelle belegt sein. Wenn eine Aussage im Input vorkommt, dort aber keine Quelle dafür steht, lasse diese Aussage weg.
- Vermeide interne Abschnittsverweise oder Nummerierungen aus den Entwürfen.
- Kein „Wir/Ich haben herausgefunden“.
- Keine Zusammenfassung am Ende.
- Ausgabe: nur Fließtext, keine Überschrift.

[ENTWÜRFE]
{DRAFTS}
"""


SUMMARY_DEFAULT_SYSTEM_PROMPT = "<Prompt entfernt>"

SUMMARY_DEFAULT_V2_SYSTEM_PROMPT = """<Prompt entfernt>"""

SUMMARY_DEFAULT_V2_INSTRUCTIONS = """### Aufgabe
Komprimiere den folgenden wissenschaftlichen Text zu einer deutlich kürzeren Fassung (Richtwert ca. 30% der Wortzahl), aber dynamisch:
- Wenn der Text sehr informationsdicht ist, darf die Ausgabe länger sein (z. B. bis ~40%).
- Wenn der Text wenig Informationsgehalt hat, kürze stärker (z. B. bis ~20%).
Wichtig: Lieber etwas länger als dass zentrale Informationen fehlen.

### Was du behalten sollst
- Behalte die inhaltlichen Kernaussagen, Definitionen, zentrale Konzepte, Prozesslogik, Abgrenzungen, Bedingungen und Einschränkungen, soweit sie im Text enthalten sind.
- Behalte Namen/Jahreszahlen nur, wenn sie für das Verständnis oder die inhaltliche Aussage relevant sind.
- Behalte die Reihenfolge der Inhalte wie im Original (es soll eine kürzere Version desselben Textes bleiben).

### Was du entfernen sollst
- Entferne Rhetorik, Ausschmückungen, Wiederholungen, Beispiele, Füllwörter und Meta-Formulierungen, sofern sie nicht essenziell für die Aussage sind.
- Entferne Quellenangaben/Zitate und Seitenzahlen (z. B. (Autor, Jahr), S. X), außer Namen/Jahre sind inhaltlich notwendig (dann ohne Zitierklammern formulieren).
- Keine Verweise auf externe Inhalte, Abbildungen oder „siehe oben/unten“.

### Stilvorgaben
- Schreibe Fließtext (keine Bulletpoints), mehrere Absätze sind erlaubt.
- Maximale Informationsdichte: kurze Sätze, wenig Stoppwörter, „telegrammstil“ ist okay.
- Keine neuen Erklärungen hinzufügen. Wenn eine Präzisierung nötig ist, nur dann, wenn sie eindeutig aus dem Text hervorgeht.

### Ausgabe
Gib ausschließlich den komprimierten Text aus.

### Text
{KAPITELTEXT}
"""

SHORTEN_DEFAULT_V2_SYSTEM_PROMPT = """<Prompt entfernt>"""

SHORTEN_DEFAULT_V2_INSTRUCTIONS = """# ZIEL
Kürze den Text, ohne den Grundstil umzubauen. Kein fixes Kürzungsziel.
Fokus: Qualität erhöhen durch Entfernen/Kürzen von unnötigen, schwachen, redundanten oder offensichtlich off-topic Passagen.
Lieber etwas weniger kürzen als Informationsverlust.

# ENTSCHEIDUNGSLOGIK (wichtig)
1) Themen-Fit: Behalte Inhalte, die direkt zur Überschrift und zum Thema passen.
2) Kapitel-Kontext nutzen, aber NICHT als Quelle:
   - Der Kontext anderer Kapitel dient nur dazu zu entscheiden, was hier redundant ist.
   - Aus dem Kontext darf nichts neu in den Text übernommen werden (keine Ergänzungen).
3) Redundanzregel:
   - Wiederholungen im Text selbst dürfen zusammengeführt/verkürzt werden.
   - Wiederholungen dürfen bleiben, wenn sie kurz und bewusst zur Klarstellung beitragen.
4) Deduplizierung über Kapitel:
   - Wenn etwas in einem vorherigen Kapitel bereits ausführlich behandelt wurde: hier nur kurz erwähnen oder streichen.
   - Wenn die Formulierung hier deutlich besser/konkreter ist: nicht streichen, sondern kürzer fassen.

# ZITATE/QUELLEN (Autor-Jahr bleibt)
- Behalte alle Zitate inhaltlich passend bei (z. B. (Name, Jahr)).
- Keine neuen Quellen, keine neuen Seitenzahlen, keine erfundenen Angaben.
- Seitenangaben lokalisieren:
  - p. X → S. X
  - pp. X–Y → S. X–Y
- Entferne eine Quelle nur, wenn die dazugehörige Aussage vollständig entfernt wurde.
- Wenn unklar, ob eine Quelle noch passt: Quelle beibehalten.
- Keine Semikolons im Fließtext. Ausnahme: nur zur Trennung mehrerer Quellen innerhalb einer Klammer (Autor, Jahr; Autor, Jahr).

# STIL/FORMAT
- Output: nur Fließtext, Absätze erlaubt.
- Keine Überschrift ausgeben, keine Schlusszusammenfassung, keine Meta-Kommentare.
- Kein „Wir/Ich haben herausgefunden“.
- Keine Listen/Bullets.

# INPUTS
Der Text an dem du arbeiten sollst ist ein Kapitel einer längeren Wissenschaftlichen Arbeit. Das Kapitel hat die Überschrift die du unten siehst und das topic ist ein kleiner Text zu dem Kapitel der beschreibt um was es in dem Kapitel gehen soll:
<heading>
{KAPITEL_TITEL}
</heading>

<topic>
{KAPITEL_BESCHREIBUNG}
</topic>

Das folgende ist Quasi die Gliederung der gesamten arbeit und zu manchen Kapitel gebe ich dir eine gekürzte Version des Textes damit du verstehst wie sich der Text an dem wir arbeiten in den Rest der gesamten Arbeit einordnet und du verstehen kannst was schon bahndelt wurde oder was noch behandelt wird.
<context_other_chapters>
{GLIEDERUNG_SUMMARY}
</context_other_chapters>

Das ist der Text an dem wir Arbeiten:
<text_to_shorten>
{KAPITELTEXT}
</text_to_shorten>

# LETZTE PRÜFUNG (intern, nicht ausgeben)
- Nichts ergänzt? Keine neuen Fakten?
- Zitate noch passend und korrekt (p./pp. → S.)?
- Keine Semikolons außer in Quellenklammern?
- Keine Überschrift im Output?
"""

LESEFLUSS_DEFAULT_V2_SYSTEM_PROMPT = """<Prompt entfernt>"""

LESEFLUSS_DEFAULT_V2_INSTRUCTIONS = """# ZIEL
Überarbeite den angegebenen Kapiteltext so, dass er sich nahtlos in die Gesamtarbeit einfügt: besserer Lesefluss, konsistente Erzähl- und Argumentationslinie, weniger Wiederholungen über Kapitel hinweg, klare Querverweise auf bereits behandelte oder kommende Inhalte und eine organische Überleitung zum nächsten Kapitel. Keine Meta-Kommentare, keine zusätzlichen Erklärungen, nur der finale Kapiteltext.

# INPUTS (klar getrennt)
<aufgabenstellung>
{AUFGABENSTELLUNG}
</aufgabenstellung>

<gliederung_und_kapitelzusammenfassungen>
{GLIEDERUNG_SUMMARY}
</gliederung_und_kapitelzusammenfassungen>

<kapiteltext_zu_ueberarbeiten>
{KAPITELTEXT}
</kapiteltext_zu_ueberarbeiten>

# KERNREGELN
1) Nur bereitgestellte Informationen nutzen
- Nutze ausschließlich Informationen aus dem Kapiteltext und aus der Gliederung/Zusammenfassung.
- Du darfst Inhalte aus anderen Kapiteln in knapper Form in den aktuellen Kapiteltext integrieren, WENN diese Inhalte in der Gliederung/Zusammenfassung stehen.
- Keine Ergänzungen aus eigenem Wissen. Keine neuen Konzepte, Definitionen, Beispiele, Zahlen oder Behauptungen, die nicht in den Inputs stehen.
- Keine neuen Kapitel erfinden.

2) Kohärenz und Querverweise (Kapitel als „roter Faden“)
- Verweise auf andere Kapitel nur im Format: „wie in Kapitel X.Y beschrieben“ oder „wie in Kapitel X erläutert“.
- Entscheide kontextabhängig:
  a) Nur Verweis ohne Wiederholung, wenn die Info dort ausreichend behandelt ist und hier nicht kritisch gebraucht wird.
  b) Kurze Wiederholung + Verweis, wenn die Info für die lokale Argumentation wichtig ist oder das referenzierte Kapitel deutlich weiter entfernt liegt.
- Wenn ein Inhalt in späteren Kapiteln vertieft wird, bereite ihn im aktuellen Kapitel so vor, dass die Vertiefung natürlich wirkt, ohne anzukündigen „dies leitet über“.

3) Redundanz-Management über Kapitel hinweg
- Identifiziere Wiederholungen zwischen dem Kapiteltext und der Gliederung/Zusammenfassung anderer Kapitel.
- Kürze oder streiche Wiederholungen, wenn sie nicht nötig sind.
- Wenn die Formulierung im aktuellen Kapitel besonders präzise ist, behalte sie in verkürzter Form und setze ggf. einen Verweis.
- Wiederholungen dürfen bleiben, wenn sie bewusst kurz zur Klarstellung beitragen und den Lesefluss verbessern.

4) Harmonisierung ohne Aggressivität
- Wenn Darstellung oder Schwerpunktsetzung zwischen Kapiteln leicht abweicht, harmonisiere vorsichtig:
  - Formuliere so um, dass Begriffe und Logik konsistent wirken.
  - Keine starken inhaltlichen „Uminterpretationen“.
  - Wenn eine Spannung bestehen bleibt, deute sie dezent an und verweise auf das Kapitel, in dem es differenziert wird.

5) Überleitung zum nächsten Kapitel (integriert, nicht angehängt)
- Baue in den letzten Absätzen des Kapiteltexts einen spürbaren, aber subtilen Übergang zum nächsten Kapitel ein.
- Keine separaten Überleitungsabsätze, keine Formulierungen wie „dies leitet über“.
- Der Übergang soll motivieren weiterzulesen und klar machen, warum das nächste Kapitel anschließt, ohne explizit zu erklären, dass ein Kapitelwechsel folgt.
- Nutze dafür nur Inhalte/Anknüpfungspunkte, die aus den Inputs hervorgehen, insbesondere aus dem „Nächstes Kapitel“ in der Gliederung.

# QUELLEN UND ZITATE (APA, ohne Semikolon außer zwischen Quellen)
- Behalte alle Quellen aus dem Kapiteltext bei und platziere sie an passenden Stellen, wenn Sätze umgestellt oder zusammengeführt werden.
- Du darfst Zitate APA-konformer straffen, ohne Informationsverlust:
  - z. B. „S. 43 und S. 46“ → „S. 43, 46“
  - „S. 256, 226ff.“ darfst du konsistent machen, z. B. „S. 226 ff., 256“, sofern keine Bedeutung verändert wird.
- Entferne eine Quelle nur, wenn die zugehörige Aussage vollständig gestrichen wird.
- Keine neuen Quellen hinzufügen.
- Keine Semikolons im Fließtext. Ausnahme: ausschließlich zur Trennung mehrerer Quellen innerhalb einer Klammer (Autor, Jahr; Autor, Jahr).

# STIL UND FORM
- Wissenschaftlicher Stil, gut lesbar, kohärent.
- Keine Überschriften ausgeben (die Kapitelüberschrift wird bei euch separat gehandhabt).
- Kein „Wir/Ich haben herausgefunden“.
- Keine Listen oder Bulletpoints, Fließtext mit Absätzen ist erlaubt.
- Stil soll grundsätzlich erhalten bleiben, aber Übergänge, Reihenfolge, Satzverknüpfung und Konsistenz dürfen verbessert werden.

# AUSGABE
Gib ausschließlich den final überarbeiteten Kapiteltext aus.
"""

DEFAULT_INSTRUCTIONS = {
    "process_quelle": """<Prompt entfernt>""",
    "combine": """[AUFGABE]
Füge die folgenden Entwürfe zu einem kohärenten wissenschaftlichen Fließtext zusammen.

Titel (nur Kontext, NICHT ausgeben): {KAPITEL_TITEL}
Thema: {KAPITEL_BESCHREIBUNG}

[ENTWÜRFE]
{DRAFTS}
""",
    "shorten": """# ZIEL
Kürze den Kapiteltext, ohne Informationsverlust, und entferne Redundanzen.

<kapitel_titel>
{KAPITEL_TITEL}
</kapitel_titel>

<kapitel_beschreibung>
{KAPITEL_BESCHREIBUNG}
</kapitel_beschreibung>

<gliederung_und_kapitelzusammenfassungen>
{GLIEDERUNG_SUMMARY}
</gliederung_und_kapitelzusammenfassungen>

<kapiteltext>
{KAPITELTEXT}
</kapiteltext>
""",
    "lesefluss": """# ZIEL
Überarbeite den Kapiteltext so, dass er sich nahtlos in die Gesamtarbeit einfügt (Lesefluss, Querverweise, weniger Redundanz).

<aufgabenstellung>
{AUFGABENSTELLUNG}
</aufgabenstellung>

<gliederung_und_kapitelzusammenfassungen>
{GLIEDERUNG_SUMMARY}
</gliederung_und_kapitelzusammenfassungen>

<kapiteltext_zu_ueberarbeiten>
{KAPITELTEXT}
</kapiteltext_zu_ueberarbeiten>
""",
    "summary": """### Aufgabe
Komprimiere den folgenden Text zu einer deutlich kürzeren Fassung, ohne neue Inhalte hinzuzufügen.

### Text
{KAPITELTEXT}
""",
}


class PromptService:
    REQUIRED_PLACEHOLDERS = {
        "process_quelle": [
            "{KAPITEL_TITEL}",
            "{KAPITEL_BESCHREIBUNG}",
            "{OPTIONAL_GRUNDLEGENDE_INFOS}",
            "{QUELLE_ZITAT}",
            "{QUELLTEXT}",
        ],
        "combine": ["{KAPITEL_TITEL}", "{KAPITEL_BESCHREIBUNG}", "{DRAFTS}"],
        "summary": ["{KAPITELTEXT}"],
        "shorten": [
            "{KAPITEL_TITEL}",
            "{KAPITEL_BESCHREIBUNG}",
            "{GLIEDERUNG_SUMMARY}",
            "{KAPITELTEXT}",
        ],
        "lesefluss": ["{AUFGABENSTELLUNG}", "{GLIEDERUNG_SUMMARY}", "{KAPITELTEXT}"],
    }

    def __init__(self):
        pass

    def _is_system_template_usable(self, tpl: dict | None) -> bool:
        if not tpl:
            return False
        if tpl.get("published", True) is not True:
            return False
        if tpl.get("archived", False) is True:
            return False
        return True

    def _ts_sort_key(self, tpl: dict) -> datetime:
        ts = tpl.get("updatedAt") or tpl.get("createdAt")
        try:
            if hasattr(ts, "to_datetime"):
                ts = ts.to_datetime()
        except Exception:
            ts = None
        return ts if isinstance(ts, datetime) else datetime.min

    async def _get_newest_system_template_key(self, stage: str) -> str | None:
        try:
            templates = await firebase_service.list_system_prompt_templates(stage)
        except Exception:
            templates = []

        candidates: list[dict] = []
        for tpl in templates:
            if not self._is_system_template_usable(tpl):
                continue
            if not (str((tpl.get("templateKey") or "")).strip()):
                continue
            if not (str((tpl.get("instructions") or "")).strip()):
                continue
            candidates.append(tpl)

        if not candidates:
            return None

        candidates.sort(key=self._ts_sort_key, reverse=True)
        key = str((candidates[0].get("templateKey") or "")).strip()
        return key or None

    async def get_instructions_for_template(
        self, user_id: str, stage: str, template_id: str | None
    ) -> str:
        """
        Return instructions for a specific template choice.

        Supported template IDs:
        - "default": system default prompt (server-only, stored in Firestore)
        - "default_v2": system v2 prompt (server-only, stored in Firestore)
        - any other existing system templateKey: server-only, stored in Firestore
        - any other string: user-owned promptTemplates/{templateId}
        """
        tid = (template_id or "").strip() or "default"

        sys_tpl = await firebase_service.get_system_prompt_template(stage, tid)
        if sys_tpl:
            if self._is_system_template_usable(sys_tpl) and (sys_tpl.get("instructions") or "").strip():
                return sys_tpl["instructions"]

            # System template exists but is unavailable/empty -> fall back to the newest available system template.
            fallback_key = await self._get_newest_system_template_key(stage)
            if fallback_key and fallback_key != tid:
                fallback_tpl = await firebase_service.get_system_prompt_template(stage, fallback_key)
                if (
                    fallback_tpl
                    and self._is_system_template_usable(fallback_tpl)
                    and (fallback_tpl.get("instructions") or "").strip()
                ):
                    return fallback_tpl["instructions"]

        if tid in {"default", "default_v2"} and not sys_tpl:
            # Firestore not seeded / missing docs -> fall back to code defaults to keep the app functional.
            if stage == "process_quelle" and tid == "default_v2":
                return PROCESS_QUELLE_DEFAULT_V2_INSTRUCTIONS
            if stage == "combine" and tid == "default_v2":
                return COMBINE_DEFAULT_V2_INSTRUCTIONS
            if stage == "summary" and tid == "default_v2":
                return SUMMARY_DEFAULT_V2_INSTRUCTIONS
            if stage == "shorten" and tid == "default_v2":
                return SHORTEN_DEFAULT_V2_INSTRUCTIONS
            if stage == "lesefluss" and tid == "default_v2":
                return LESEFLUSS_DEFAULT_V2_INSTRUCTIONS
            return DEFAULT_INSTRUCTIONS.get(stage, "")

        tpl = await firebase_service.get_prompt_template(user_id, tid)
        if tpl and (tpl.get("instructions") or "").strip():
            return tpl["instructions"]

        # Unknown template id → safe fallback.
        sys_tpl = await firebase_service.get_system_prompt_template(stage, "default")
        if sys_tpl and self._is_system_template_usable(sys_tpl) and (sys_tpl.get("instructions") or "").strip():
            return sys_tpl["instructions"]
        return DEFAULT_INSTRUCTIONS.get(stage, "")

    async def get_instructions(self, user_id: str, stage: str) -> str:
        """Return active instructions for a stage or default."""
        active_id = (await firebase_service.get_active_prompt_id(user_id, stage)) or "default"
        active_id = (active_id or "").strip() or "default"

        # If the user selected an archived/unpublished system template, auto-migrate them to the newest one.
        sys_tpl = await firebase_service.get_system_prompt_template(stage, active_id)
        if sys_tpl and (
            not self._is_system_template_usable(sys_tpl) or not (sys_tpl.get("instructions") or "").strip()
        ):
            fallback_key = await self._get_newest_system_template_key(stage)
            next_id = fallback_key or "default"
            if next_id and next_id != active_id:
                try:
                    await firebase_service.set_active_prompt_id(user_id, stage, next_id)
                    active_id = next_id
                except Exception:
                    # Safe fallback: don't block the request if the migration write fails.
                    active_id = next_id

        return await self.get_instructions_for_template(user_id, stage, active_id)

    async def get_system_prompt_for_template(
        self,
        *,
        stage: str,
        template_id: str | None,
    ) -> str | None:
        """
        Return a system prompt override for a given template choice (if provided).

        For now, only server-only system templates can define a system prompt.
        User templates use the stage's built-in system prompt in code.
        """
        tid = (template_id or "").strip() or "default"

        sys_tpl = await firebase_service.get_system_prompt_template(stage, tid)
        if sys_tpl and not self._is_system_template_usable(sys_tpl):
            # If the selected system template is unavailable, fall back to the newest available one.
            fallback_key = await self._get_newest_system_template_key(stage)
            if fallback_key and fallback_key != tid:
                tid = fallback_key
                sys_tpl = await firebase_service.get_system_prompt_template(stage, tid)

        if sys_tpl and self._is_system_template_usable(sys_tpl):
            system_prompt = str(((sys_tpl or {}).get("systemPrompt") or "")).strip()
            if system_prompt:
                return system_prompt
            # Non-default system templates may omit systemPrompt to fall back to the stage's default system message.
            if tid not in {"default", "default_v2"}:
                return None

        if tid not in {"default", "default_v2"}:
            return None

        if stage == "process_quelle":
            if tid == "default_v2":
                return PROCESS_QUELLE_DEFAULT_V2_SYSTEM_PROMPT
            if tid == "default":
                return PROCESS_QUELLE_DEFAULT_SYSTEM_PROMPT

        if stage == "combine":
            if tid == "default_v2":
                return COMBINE_DEFAULT_V2_SYSTEM_PROMPT
            if tid == "default":
                return COMBINE_DEFAULT_SYSTEM_PROMPT

        if stage == "summary":
            if tid == "default_v2":
                return SUMMARY_DEFAULT_V2_SYSTEM_PROMPT
            if tid == "default":
                return SUMMARY_DEFAULT_SYSTEM_PROMPT

        if stage == "shorten":
            if tid == "default_v2":
                return SHORTEN_DEFAULT_V2_SYSTEM_PROMPT
            return None

        if stage == "lesefluss":
            if tid == "default_v2":
                return LESEFLUSS_DEFAULT_V2_SYSTEM_PROMPT
            return None

        return None

    def render(self, instructions: str, payload: dict) -> str:
        rendered = instructions
        for key, value in payload.items():
            rendered = rendered.replace(f"{{{key}}}", str(value or ""))
        return rendered

    def _ensure_process_quelle_quelle_zitat_placeholder(self, instructions: str) -> str:
        """
        Backward-compatible injection: ensure {QUELLE_ZITAT} exists in process_quelle templates,
        even if older stored templates don't include it yet.
        """
        text = instructions or ""
        if "{QUELLE_ZITAT}" in text:
            return text

        # Append as a safe fallback (lets authors decide placement in their templates).
        return text.rstrip() + "\n\n{QUELLE_ZITAT}\n"

    async def get_rendered_instructions(
        self, user_id: str, stage: str, payload: dict
    ) -> str:
        base = await self.get_instructions(user_id, stage)
        if stage == "process_quelle":
            base = self._ensure_process_quelle_quelle_zitat_placeholder(base)
        return self.render(base, payload)

    async def get_rendered_instructions_for_template(
        self,
        user_id: str,
        stage: str,
        template_id: str | None,
        payload: dict,
    ) -> str:
        base = await self.get_instructions_for_template(user_id, stage, template_id)
        if stage == "process_quelle":
            base = self._ensure_process_quelle_quelle_zitat_placeholder(base)
        return self.render(base, payload)


prompt_service = PromptService()
