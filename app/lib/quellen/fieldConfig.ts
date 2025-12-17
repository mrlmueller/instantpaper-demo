export const QUELLE_TYPES = [
  'Book',
  'Article',
  'Website',
  'Thesis',
  'Report',
] as const;

export type QuelleType = typeof QUELLE_TYPES[number];

export const QUELLE_COLORS = [
  'light-blue',
  'mint',
  'peach',
  'lavender',
  'pink',
  'yellow',
  'coral',
] as const;

export type QuelleColor = typeof QUELLE_COLORS[number];

// Color to Tailwind class mapping (pastel palette)
export const COLOR_CLASSES: Record<QuelleColor, string> = {
  'light-blue': 'bg-blue-100 border-blue-300 text-blue-900',
  'mint': 'bg-emerald-100 border-emerald-300 text-emerald-900',
  'peach': 'bg-orange-100 border-orange-300 text-orange-900',
  'lavender': 'bg-purple-100 border-purple-300 text-purple-900',
  'pink': 'bg-pink-100 border-pink-300 text-pink-900',
  'yellow': 'bg-yellow-100 border-yellow-300 text-yellow-900',
  'coral': 'bg-red-100 border-red-300 text-red-900',
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
