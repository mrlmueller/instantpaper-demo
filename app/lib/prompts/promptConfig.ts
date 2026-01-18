import type { PromptStage } from "@/app/types/prompts";

type StageConfig = {
  label: string;
  requiredPlaceholders: string[];
  optionalPlaceholders?: string[];
  sampleData: Record<string, string>;
  defaultInstructions: string;
  tooltip?: string;
};

export const LEGACY_SYSTEM_PROMPT_TEMPLATE_KEY = "default";
export const DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY = "default_v2";

const DEFAULT_PROMPT_STUB = ``;

export const STAGE_CONFIG: Record<PromptStage, StageConfig> = {
  process_quelle: {
    label: "Quellen verarbeiten",
    requiredPlaceholders: [
      "{KAPITEL_TITEL}",
      "{KAPITEL_BESCHREIBUNG}",
      "{OPTIONAL_GRUNDLEGENDE_INFOS}",
      "{QUELLE_ZITAT}",
      "{QUELLTEXT}",
    ],
    tooltip:
      "Pflicht-Platzhalter: {KAPITEL_TITEL}, {KAPITEL_BESCHREIBUNG}, {OPTIONAL_GRUNDLEGENDE_INFOS}, {QUELLE_ZITAT}, {QUELLTEXT}. Bilder werden automatisch mitgesendet (falls vorhanden).",
    sampleData: {
      KAPITEL_TITEL: "Digitale Transformation in KMU",
      KAPITEL_BESCHREIBUNG: "Einfluss von KI auf Effizienzgewinne",
      OPTIONAL_GRUNDLEGENDE_INFOS: "Konzentriere dich auf deutschsprachige Quellen mit Seitenzahlen.",
      QUELLE_ZITAT: "Schmidt, 2023",
      QUELLTEXT: "Beispiel-Quelltext ...",
    },
    defaultInstructions: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
  },
  combine: {
    label: "Texte kombinieren",
    requiredPlaceholders: ["{KAPITEL_TITEL}", "{KAPITEL_BESCHREIBUNG}", "{DRAFTS}"],
    tooltip:
      "Pflicht-Platzhalter: {KAPITEL_TITEL}, {KAPITEL_BESCHREIBUNG}, {DRAFTS}.",
    sampleData: {
      KAPITEL_TITEL: "Auswirkungen von KI",
      KAPITEL_BESCHREIBUNG: "Produktivitaetsgewinne in der Industrie",
      DRAFTS: "Text 1:\n...\n\nText 2:\n...",
    },
    defaultInstructions: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
  },
  shorten: {
    label: "Kuerzen & Entduplizieren",
    requiredPlaceholders: ["{KAPITEL_TITEL}", "{KAPITEL_BESCHREIBUNG}", "{GLIEDERUNG_SUMMARY}", "{KAPITELTEXT}"],
    tooltip:
      "Pflicht-Platzhalter: {KAPITEL_TITEL}, {KAPITEL_BESCHREIBUNG}, {GLIEDERUNG_SUMMARY}, {KAPITELTEXT}.",
    sampleData: {
      KAPITEL_TITEL: "Kapitel 2.1 - Methodik",
      KAPITEL_BESCHREIBUNG: "Vergleich von Klassifikationsverfahren",
      GLIEDERUNG_SUMMARY: "2.1 Methodik\n2.1.1 Datenerhebung ...",
      KAPITELTEXT: "Langer Beispieltext ...",
    },
    defaultInstructions: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
  },
  lesefluss: {
    label: "Lesefluss verbessern",
    requiredPlaceholders: ["{AUFGABENSTELLUNG}", "{GLIEDERUNG_SUMMARY}", "{KAPITELTEXT}"],
    tooltip:
      "Pflicht-Platzhalter: {AUFGABENSTELLUNG}, {GLIEDERUNG_SUMMARY}, {KAPITELTEXT}.",
    sampleData: {
      AUFGABENSTELLUNG: "Analyse der Auswirkungen von KI auf die Arbeitswelt.",
      GLIEDERUNG_SUMMARY: "Kapitel 1 ...",
      KAPITELTEXT: "Der aktuelle Text ist ...",
    },
    defaultInstructions: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
  },
  summary: {
    label: "Zusammenfassung",
    requiredPlaceholders: ["{KAPITELTEXT}"],
    tooltip: "Pflicht-Platzhalter: {KAPITELTEXT}.",
    sampleData: { KAPITELTEXT: "Beispieltext der zusammengefasst werden soll." },
    defaultInstructions: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
  },
};

export const MAX_TEMPLATES_PER_STAGE = 10;
export const MAX_NAME_LENGTH = 80;
export const MIN_NAME_LENGTH = 3;
