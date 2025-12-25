from services.firebase_service import firebase_service
import logging

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
1) Der Absatz behandelt wirklich nur {ANWEISUNGEN} (Randinfos sind ok, solange thematisch anschlussfähig).
2) Keine erfundenen Fakten.
3) Jede fachliche Behauptung aus dem Quelltext hat eine passende APA-Zitation.
4) Keine internen Abschnitts-/Kapitelverweise übernommen.
5) Text ist eindeutig neu formuliert und einzigartig.

[GRUNDLEGENDE INFORMATIONEN – OPTIONAL]
{GRUNDLEGENDE_INFOS_ODER_LEER}

Quelltext:
{QUELLTEXT}

Bildinhalte (falls vorhanden):
{BILDINHALT_ODER_LEER}
"""


COMBINE_DEFAULT_SYSTEM_PROMPT = "<Prompt entfernt>"

COMBINE_DEFAULT_V2_SYSTEM_PROMPT = """<Prompt entfernt>"""

COMBINE_DEFAULT_V2_INSTRUCTIONS = """[AUFGABE]
Füge die folgenden Entwürfe zu einem kohärenten wissenschaftlichen Fließtext zusammen. Der Fließtext ist Teil einer großeren Arbeit. Das Kapitel das du schreiben sollst, 
hat den titel den du unten siehst und behandelt das Thema das du ebenfalls unten siehst. Thema ist einfach nur ein kleiner Text der beschreibt um was es in dem Kapitel genau gehen soll.

Titel (nur Kontext, NICHT ausgeben): {heading}
Thema: {topic}

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


SUMMARY_DEFAULT_SYSTEM_PROMPT = (
    "<Prompt entfernt>"
)

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
{text}
"""

DEFAULT_INSTRUCTIONS = {
    "process_quelle": (
        "### Aufgabe:\n"
        "Schreibe einen Absatz in einer wissenschaftlichen Arbeit. Da es nur ein Absatz ist, schreibe keine Einleitung oder Schlussfolgerung/Zusammenfassung. "
        'Der Absatz hat die Überschrift "{heading}" und soll genauer das Thema "{topic}" behandeln. Beziehe dich beim Schreiben des Absatzes nur auf die oben gegebenen Informationen '
        "und nutze nichts aus deinem eigenen Wissen. Fokussiere dich außerdem genau auf das Thema, das ich vorgegeben habe, da andere Informationen hierzu bereits behandelt worden sind "
        "oder noch behandelt werden; kurzum, schreibe wirklich nur über das vorgegebene Thema. Wichtig ist, dass Informationen, die aus dem obigen Text übernommen werden, so umgeschrieben "
        "werden sollen, dass der obige Text nicht mehr zu erkennen ist - das Ergebnis also einzigartig ist. Der Text soll so lang sein, wie er sein muss, um alle relevanten Informationen "
        "zu integrieren; ziehe ihn nicht unnötig in die Länge, aber lasse auch nichts Relevantes weg. Sollte der Text keine sinnvollen Informationen zu dem gegebenen Thema enthalten, kannst "
        "du mir das sagen und den Text dann nicht schreiben; gib mir dann eine kurze Erklärung, warum der Text nicht zum Thema gepasst hat. Integriere außerdem die Quellen (mit Seitenzahlen, "
        "wenn diese gegeben wurden) aus dem oberen Text an den richtigen Stellen. Der gegebene Text hat sicherlich mehr Informationen zu manchen Themen und weniger zu anderen. Fokussiere dich "
        "auf die Themen, zu denen du wirklich konkrete und tiefe Einblicke geben kannst. Dieser Text ist nur einer von 10, die ich zu diesem Thema habe. Das bedeutet, wenn du eine Dimension "
        "nur wenig oder gar nicht behandelst, habe ich dennoch viele Informationen zu dieser in einem anderen Text. Genauer ausgedrückt, schreibst du gerade einen von 10 Texten, die später das "
        "Kapitel ergeben werden. Das bedeutet auch, dass du dich wirklich auf das Wichtigste beschränken kannst und nicht unnötiges schreiben musst. Schreibe keine Zusammenfassung oder "
        "Schlussfolgerung am Ende. Nur reine Informationen. Formuliere den Text ohne dass du ; verwendest, außer zwischen zwei Quellen."
    ),
    "combine": (
        "### Aufgabe:\n"
        "<Prompt entfernt>"
        "enthalten sind. Identifiziere Informationen, die doppelt behandelt werden, und stelle sicher, dass diese Informationen nur noch einmal in deinem Text behandelt werden. Der Text, den du "
        'schreiben sollst, hat den Titel "{heading}" und hat das Thema "{topic}". Wenn du den Text neu schreibst aufgrund der gegebenen Texte, gehe sicher, dass du nicht einfach nur die Themen '
        "aneinander hängst, sondern dass du einerseits die gesamte Struktur so veränderst, dass dein Text Sinn ergibt; du kannst auch die Informationen nutzen, um neue Schlüsse zu ziehen im Sinne "
        "des gegebenen Themas. Du kannst alles machen, das Ziel ist nur, das bestmögliche Endergebnis zu erstellen. Aber du sollst nur die gegebenen Informationen nutzen und keine Informationen aus "
        "deinem eigenen Wissen mit einbeziehen! Schreibe keine Zusammenfassung am Ende, da dies nur ein Teil eines längeren Textes ist. Habe Spaß mit der Findung deines Textes, untersuche "
        "verschiedene Aspekte deiner Argumente und gib somit eine Antwort mit sehr viel Nuance. Schreibe einen zusammenhängenden Text ohne Zwischenüberschriften. Du musst dich bei deinem Text nicht "
        "kurz fassen, schreibe deinen Text so lange, wie er sein muss, bis du alle Informationen integriert und alle Argumente ausreichend beschrieben hast, ich begrüße es sogar, wenn du einen "
        'längeren Text schreibst; wichtig ist aber auch, dass du deinen Text nicht künstlich in die Länge ziehst. Schreibe ohne "Wir/Ich haben herausgefunden". Integriere auch hier die Quellen '
        "mit Seitenzahlen. Nutze nur die Informationen, die in den Texten gegeben sind, ergänze nichts dazu, das nicht in den Texten steht. Wenn du Argumente beschreibst, gehe sicher, immer eine "
        "Quelle zu integrieren. Formuliere den Text ohne dass du ; verwendest, außer zwischen zwei Quellen."
    ),
    "shorten": (
        "### Aufgabe:\n"
        'Ich schreibe gerade eine Wissenschaftliche Arbeit. Der folgende Text ist bereits gut, so wie er ist, allerding ist er noch zu lang. Aber damit du optimal den Text kürzen kannst, also dass du den Fokus auf die richtigen Fakten und Themen legen kannst, werde ich dir die Überschrift "{ueberschrift}" und auch das Thema des Textes geben "{thema}". Zusätzlich werde ich dir folgend einen Teil meiner Gliederung geben zusammen mit einer zusammengefassten Version der Texte von den anderen Kapitel und Unterpunkten der Kapitel. All dies gebe ich dir, damit du perfekt entscheiden kannst, auf was der Fokus gelegt werden sollte in der Arbeit. Konkret ist deine Aufgabe, den Text auf die Hälfte oder noch etwas weniger zu kürzen, aber dabei alle wichtigen Informationen beizubehalten. Behalte auch sämtliche Quellen an den richtigen Stellen bei außer, wenn du eine Information zu einer Quelle komplett eliminierst. Du sollst nur die gegebenen Informationen nutzen und keine Informationen aus deinem eigenen Wissen einbeziehen! Schreibe keine Zusammenfassung am Ende, da dies nur ein Teil eines längeren Textes ist. Habe Spaß mit der Findung deines Textes. Schreibe ohne "Wir/Ich haben herausgefunden". Schreibe aber dennoch so, dass es Spaß macht, den Text zu lesen, also dass es kein zu trockener Text wird, aber behalte dennoch die Wissenschaftliche Schreibweise bei. Wenn du Argumente beschreibst, gehe sicher, immer eine Quelle zu integrieren. Formuliere den Text ohne dass du ; verwendest, außer zwischen zwei Quellen.\n\nWICHTIG: Antworte mit einem JSON-Objekt wie im System-Prompt beschrieben. Gebe eine kurze Erklärung deiner Entscheidungen im explanation-Feld und den gekürzten Text im shortened_text-Feld.'
    ),
    "lesefluss": (
        "### Aufgabe\n"
        "Ich schreibe gerade meine Wissenschaftlichen Arbeit.\n"
        'Momentan sind die Texte aus den verschiedenen Unterkapiteln noch sehr "alleinstehend" was ich meine ist das in den einzelnen Unterkapitel nicht auf die Folgenden oder kommenden Kapitel eingegangen wird und der Text somit noch sehr gestückelt und keine Gesamtheit ist. Auch kommen Informationen doppelt vor oder das Thema wird unterschiedlich behandelt in verschiedenen Unterkapiteln.\n'
        "Für einen besseren Kontext für dich ist hier die Aufgabenstellung für die gesamte Arbeit:\n\n"
        "AUFGABENSTELLUNG:\n{aufgabenstellung}\nAUFGABENSTELLUNG ENDE\n\n"
        "Ich werde dir außerdem eine zusammengefasste Version der ganzen Arbeit geben. Zu jedem Unterkapitel gibt es einen am Anfang kleinen Text der beschreibt was in diesem Unterkapitel für Informationen behandelt werden. Allerdings sind die Texte zusammengefasst, da die ganze Arbeit zu lang wäre. Berücksichtige diese Information wenn die auf ein Kapitel verweist. Dies ist damit du einen besseren Kontext für die ganze Arbeit hast. Du kannst auch auf Informationen die hier bearbeitet wurden verweisen.\n"
        'Ich will von dir das du einen fließenden Text aus dem ganzen machst, dass in dem Text an dem du gerade Arbeitest auf bereits behandelte Informationen verwiesen werden kann, wenn das Sinn macht, oder das darauf verwiesen wird, das etwas noch tiefer bearbeitet werden wird in einem kommenden Kapitel. Wenn du auf ein anderes Kapitel verweist, dann schreibe nicht "wie in 2.2 beschrieben." sondern "wie in Kapitel 2.2 beschrieben." also schreibe dazu das du auf das Kapitel xy verweist.\n'
        'Nutze die letzten Absätze deines Textes dazu, eine subtile Überleitung in das nächste Kapitel einzuweben. Schreibe nicht einfach am ende einen kurzen Absatz in dem du überleitest. Der Lesefluss soll nicht unterbrochen werden. Schreibe auch nicht "dies leitet über". Gebe dir Mühe bei der Überleitung da dies den Text Charakter verleiht. Habe Spaß mit der Findung. Nutze nur die Informationen die in den Texten gegeben sind, ergänze nichts dazu, das nicht in den Texten steht.. Übernehme außerdem die angegebenen Quellen (mit Seitenzahlen, wenn Seitenzahlen in der Quelle vorhanden sind) in deinen Text. Gehe sicher, dass keine Informationen weggelassen werden. Erfinde aber auch keine zusätzlichen Kapitel oder Informationen hinzu. Was du aber machen kannst ist zusätzliche Informationen so zu nutzen das neue Schlüsse gezogen werden, gehe aber sicher diese dann immer so zu formulieren das klar wird das es sich hier um dein Gedankengut und nicht um Wissenschaftlich bewiesenes geht. Formuliere den Text ohne das du ; verwendest, außer zwischen zwei Quellen.\n'
        "Schreibe am Ende, wenn du den Text komplett überarbeitet hast, kurz zwei Sätze, zu was du verändert hast."
    ),
    "summary": (
        "### Aufgabe:\n"
        "Fasse folgenden Text zusammen, sodass er auf ungefähr 30% Wörter vom Original Text kommt. Ziel dieser Zusammenfassung ist es, die Rhetorik und nebensächliche Informationen wegzulassen, aber die grundlegenden Informationen beizubehalten. "
        "Schreibe lieber Sätze, die sich nicht flüssig lesen lassen, also ohne viele Stoppwörter sind und integriere dafür aber mehr Information. Das Ziel ist einen Text, der so kurz wie möglich, aber auch so viele Informationen wie möglich hat. Quellen können weggelassen werden.\n\n"
        "### Text:\n{text}"
    ),
}


class PromptService:
    REQUIRED_PLACEHOLDERS = {
        "process_quelle": ["{heading}", "{topic}"],
        "combine": ["{heading}", "{topic}"],
        "summary": ["{text}"],
    }

    def __init__(self):
        pass

    async def get_instructions_for_template(
        self, user_id: str, stage: str, template_id: str | None
    ) -> str:
        """
        Return instructions for a specific template choice.

        Supported template IDs:
        - "default": system default prompt (server-only, stored in Firestore)
        - "default_v2": system v2 prompt (server-only, stored in Firestore)
        - any other string: user-owned promptTemplates/{templateId}
        """
        tid = (template_id or "").strip() or "default"

        if tid in {"default", "default_v2"}:
            sys_tpl = await firebase_service.get_system_prompt_template(stage, tid)
            if sys_tpl and (sys_tpl.get("instructions") or "").strip():
                return sys_tpl["instructions"]
            # Fallback to code default if Firestore template is missing.
            if stage == "process_quelle" and tid == "default_v2":
                return PROCESS_QUELLE_DEFAULT_V2_INSTRUCTIONS
            if stage == "combine" and tid == "default_v2":
                return COMBINE_DEFAULT_V2_INSTRUCTIONS
            if stage == "summary" and tid == "default_v2":
                return SUMMARY_DEFAULT_V2_INSTRUCTIONS
            return DEFAULT_INSTRUCTIONS.get(stage, "")

        tpl = await firebase_service.get_prompt_template(user_id, tid)
        if tpl and (tpl.get("instructions") or "").strip():
            return tpl["instructions"]

        # Unknown template id → safe fallback.
        sys_tpl = await firebase_service.get_system_prompt_template(stage, "default")
        if sys_tpl and (sys_tpl.get("instructions") or "").strip():
            return sys_tpl["instructions"]
        return DEFAULT_INSTRUCTIONS.get(stage, "")

    async def get_instructions(self, user_id: str, stage: str) -> str:
        """Return active instructions for a stage or default."""
        active_id = await firebase_service.get_active_prompt_id(user_id, stage)
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
        if tid not in {"default", "default_v2"}:
            return None

        sys_tpl = await firebase_service.get_system_prompt_template(stage, tid)
        system_prompt = (sys_tpl or {}).get("systemPrompt") or ""
        system_prompt = str(system_prompt).strip()
        if system_prompt:
            return system_prompt

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

        return None

    def render(self, instructions: str, payload: dict) -> str:
        rendered = instructions
        for key, value in payload.items():
            rendered = rendered.replace(f"{{{key}}}", str(value or ""))
        return rendered

    async def get_rendered_instructions(
        self, user_id: str, stage: str, payload: dict
    ) -> str:
        base = await self.get_instructions(user_id, stage)
        return self.render(base, payload)

    async def get_rendered_instructions_for_template(
        self,
        user_id: str,
        stage: str,
        template_id: str | None,
        payload: dict,
    ) -> str:
        base = await self.get_instructions_for_template(user_id, stage, template_id)
        return self.render(base, payload)


prompt_service = PromptService()
