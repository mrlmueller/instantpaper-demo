from services.firebase_service import firebase_service
import logging

logger = logging.getLogger(__name__)


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
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        "enthalten sind. Identifiziere Informationen, die doppelt behandelt werden, und stelle sicher, dass diese Informationen nur noch einmal in deinem Text behandelt werden. Der Text, den du "
        'schreiben sollst, hat den Titel "{heading}" und hat das Thema "{topic}". Wenn du den Text neu schreibst aufgrund der gegebenen Texte, gehe sicher, dass du nicht einfach nur die Themen '
        "aneinander hängst, sondern dass du einerseits die gesamte Struktur so veränderst, dass dein Text Sinn ergibt; du kannst auch die Informationen nutzen, um neue Schlüsse zu ziehen im Sinne "
        "des gegebenen Themas. Du kannst alles machen, das Ziel ist nur, das bestmögliche Endergebnis zu erstellen. Aber du sollst nur die gegebenen Informationen nutzen und keine Informationen aus "
        "deinem eigenen Wissen mit einbeziehen! Schreibe keine Zusammenfassung am Ende, da dies nur ein Teil eines längeren Textes ist. Habe Spaß mit der Findung deines Textes, untersuche "
        "verschiedene Aspekte deiner Argumente und gib somit eine Antwort mit sehr viel Nuance. Schreibe einen zusammenhängenden Text ohne Zwischenüberschriften. Du musst dich bei deinem Text nicht "
        "kurz fassen, schreibe deinen Text so lange, wie er sein muss, bis du alle Informationen integriert und alle Argumente ausreichend beschrieben hast, ich begrüße es sogar, wenn du einen "
        "längeren Text schreibst; wichtig ist aber auch, dass du deinen Text nicht künstlich in die Länge ziehst. Schreibe ohne \"Wir/Ich haben herausgefunden\". Integriere auch hier die Quellen "
        "mit Seitenzahlen. Nutze nur die Informationen, die in den Texten gegeben sind, ergänze nichts dazu, das nicht in den Texten steht. Wenn du Argumente beschreibst, gehe sicher, immer eine "
        "Quelle zu integrieren. Formuliere den Text ohne dass du ; verwendest, außer zwischen zwei Quellen."
    ),
    "shorten": (
        "### Aufgabe:\n"
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
    ),
    "lesefluss": (
        "### Aufgabe\n"
        "Ich schreibe gerade meine Wissenschaftlichen Arbeit.\n"
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        "Für einen besseren Kontext für dich ist hier die Aufgabenstellung für die gesamte Arbeit:\n\n"
        "AUFGABENSTELLUNG:\n{aufgabenstellung}\nAUFGABENSTELLUNG ENDE\n\n"
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        "Schreibe am Ende, wenn du den Text komplett überarbeitet hast, kurz zwei Sätze, zu was du verändert hast."
    ),
    "summary": (
        "### Aufgabe:\n"
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
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

    async def get_instructions(self, user_id: str, stage: str) -> str:
        """Return active instructions for a stage or default."""
        active_id = await firebase_service.get_active_prompt_id(user_id, stage)
        if active_id and active_id != "default":
            tpl = await firebase_service.get_prompt_template(user_id, active_id)
            if tpl and tpl.get("instructions"):
                return tpl["instructions"]
        return DEFAULT_INSTRUCTIONS.get(stage, "")

    def render(self, instructions: str, payload: dict) -> str:
        rendered = instructions
        for key, value in payload.items():
            rendered = rendered.replace(f"{{{key}}}", value or "")
        return rendered

    async def get_rendered_instructions(self, user_id: str, stage: str, payload: dict) -> str:
        base = await self.get_instructions(user_id, stage)
        return self.render(base, payload)


prompt_service = PromptService()
