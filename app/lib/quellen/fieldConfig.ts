export const QUELLE_TYPES = [
  'Book',
  'Article',
  'Website',
  'Thesis',
  'Report',
] as const;

export type QuelleType = typeof QUELLE_TYPES[number];

export const QUELLE_COLORS = [
  'blue',
  'green',
  'teal',
  'lavender',
  'cream',
  'peach',
  'rose',
] as const;

export type QuelleColor = typeof QUELLE_COLORS[number];

// Color to hex code mapping (specific colors for better consistency)
export const colorMap: Record<QuelleColor, string> = {
  blue: "#64A9D2",
  green: "#91DC96",
  teal: "#95D1C4",
  lavender: "#DEBBF4",
  cream: "#DEDE8E",
  peach: "#E4A882",
  rose: "#E58283",
};

// German color labels for UI
export const colorLabels: Record<QuelleColor, string> = {
  blue: "Blau",
  green: "Grün",
  teal: "Türkis",
  lavender: "Lavendel",
  cream: "Creme",
  peach: "Pfirsich",
  rose: "Rosa",
};

// Advanced field definitions (easily extensible)
export interface QuelleFieldDefinition {
  key: string;
  label: string;
  type: 'text' | 'number' | 'select' | 'date' | 'url';
  placeholder?: string;
  options?: readonly string[];
  required?: boolean;
  validation?: (value: any) => string | null; // Returns error message or null
}

export const ADVANCED_FIELDS: QuelleFieldDefinition[] = [
  {
    key: 'autor',
    label: 'Autor',
    type: 'text',
    placeholder: 'z.B. Müller, M.',
    required: false,
  },
  {
    key: 'jahr',
    label: 'Jahr',
    type: 'number',
    placeholder: 'z.B. 2023',
    required: false,
    validation: (value) => {
      if (value && (value < 1800 || value > new Date().getFullYear() + 1)) {
        return 'Ungültiges Jahr';
      }
      return null;
    },
  },
  {
    key: 'typ',
    label: 'Typ',
    type: 'select',
    options: QUELLE_TYPES,
    required: false,
  },
  {
    key: 'url',
    label: 'URL',
    type: 'url',
    placeholder: 'https://...',
    required: false,
    validation: (value) => {
      if (value && !value.match(/^https?:\/\/.+/)) {
        return 'URL muss mit http:// oder https:// beginnen';
      }
      return null;
    },
  },
  {
    key: 'zugriffAm',
    label: 'Zugriff am',
    type: 'date',
    required: false,
  },
];
