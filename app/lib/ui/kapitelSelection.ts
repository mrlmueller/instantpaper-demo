const COOKIE_PREFIX = 'instantpaper_active_kapitel_';

export function getActiveKapitelCookieName(projektId: string): string {
  return `${COOKIE_PREFIX}${projektId}`;
}

