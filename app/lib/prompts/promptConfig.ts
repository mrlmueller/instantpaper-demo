import type { PromptStage } from "@/app/types/prompts";

type StageConfig = {
  label: string;
  requiredPlaceholders: string[];
  optionalPlaceholders?: string[];
  sampleData: Record<string, string>;
  defaultInstructions: string;
  tooltip?: string;
};

export const STAGE_CONFIG: Record<PromptStage, StageConfig> = {
  process_quelle: {
    label: "Quellen verarbeiten",
    requiredPlaceholders: ["{heading}", "{topic}"],
    optionalPlaceholders: ["{grundlegende_infos}"],
    tooltip:
      "Pflicht-Platzhalter: {heading}, {topic}. Optional: {grundlegende_infos}. Der Quellentext wird automatisch vor die Instructions gesetzt.",
    sampleData: {
      heading: "Digitale Transformation in KMU",
      topic: "Einfluss von KI auf Effizienzgewinne",
      grundlegende_infos: "Konzentriere dich auf deutschsprachige Quellen mit Seitenzahlen.",
    },
    defaultInstructions: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
  },
  combine: {
    label: "Texte kombinieren",
    requiredPlaceholders: ["{heading}", "{topic}"],
    tooltip:
      "Pflicht-Platzhalter: {heading}, {topic}. Alle Einzeltexte werden automatisch unten angehängt.",
    sampleData: {
      heading: "Auswirkungen von KI",
      topic: "Produktivitätsgewinne in der Industrie",
    },
    defaultInstructions: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
  },
  shorten: {
    label: "Kürzen & Entduplizieren",
    requiredPlaceholders: [],
    tooltip:
      "Kein Pflicht-Platzhalter. Gliederung, Kontext-Zusammenfassungen und Zieltext werden automatisch angehängt.",
    sampleData: {
      ueberschrift: "Kapitel 2.1 – Methodik",
      thema: "Vergleich von Klassifikationsverfahren",
      gliederung: "2.1 Methodik\n2.1.1 Datenerhebung ...",
      target_text: "Langer Beispieltext ...",
    },
    defaultInstructions: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
  },
  lesefluss: {
    label: "Lesefluss verbessern",
    requiredPlaceholders: [],
    tooltip:
      "Kein Pflicht-Platzhalter. Aufgabenstellung, Gliederung, Kapitelnummer und Zieltext werden automatisch angehängt.",
    sampleData: {
      aufgabenstellung: "Analyse der Auswirkungen von KI auf die Arbeitswelt.",
      gliederung: "Kapitel 1 ...",
      kapitel_nummer: "3.2",
      target_text: "Der aktuelle Text ist ...",
    },
    defaultInstructions: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
  },
  summary: {
    label: "Zusammenfassung",
    requiredPlaceholders: ["{text}"],
    tooltip: "Pflicht-Platzhalter: {text}.",
    sampleData: { text: "Beispieltext der zusammengefasst werden soll." },
    defaultInstructions: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
  },
};

export const MAX_TEMPLATES_PER_STAGE = 10;
export const MAX_NAME_LENGTH = 80;
export const MIN_NAME_LENGTH = 3;
