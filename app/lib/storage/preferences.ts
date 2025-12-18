const STORAGE_PREFIX = 'instantpaper_';

export const STORAGE_KEYS = {
  QUELLEN_PANEL_OPEN: `${STORAGE_PREFIX}quellen_panel_open`,
  QUELLEN_MODE_ADVANCED: `${STORAGE_PREFIX}quellen_mode_advanced`,
} as const;

// Helper functions for Quellen panel state
export function getQuellenPanelState(): boolean {
  if (typeof window === 'undefined') return false;
  const stored = localStorage.getItem(STORAGE_KEYS.QUELLEN_PANEL_OPEN);
  return stored === 'true';
}

export function setQuellenPanelState(open: boolean): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(STORAGE_KEYS.QUELLEN_PANEL_OPEN, String(open));
}

// Helper functions for Quellen mode preference
export function getQuellenModeAdvanced(): boolean {
  if (typeof window === 'undefined') return false;
  const stored = localStorage.getItem(STORAGE_KEYS.QUELLEN_MODE_ADVANCED);
  return stored === 'true';
}

export function setQuellenModeAdvanced(advanced: boolean): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(STORAGE_KEYS.QUELLEN_MODE_ADVANCED, String(advanced));
}
