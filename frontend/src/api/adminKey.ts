// Minimal client-side companion to backend/app/auth.py's shared-secret gate
// (AUDIT.md §1) — there's no real auth system until Clerk lands in P3, so this
// just prompts the admin (Amaan) for the key once per browser session and
// attaches it as a header. Not meant to be secure against someone reading the
// JS bundle — there's nothing embedded in the bundle to read. The key only
// ever lives in sessionStorage (cleared when the tab closes) and in the
// request header itself.

const STORAGE_KEY = "adminApiKey";

export function getStoredAdminKey(): string | null {
  return sessionStorage.getItem(STORAGE_KEY);
}

export function promptForAdminKey(): string | null {
  const key = window.prompt("Admin key (required to trigger a scrape):");
  if (key) sessionStorage.setItem(STORAGE_KEY, key);
  return key;
}

export function clearStoredAdminKey(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}

/** Returns request headers with X-Admin-Key set, prompting first if needed. */
export function adminHeaders(): { "X-Admin-Key": string } | undefined {
  const key = getStoredAdminKey() ?? promptForAdminKey();
  return key ? { "X-Admin-Key": key } : undefined;
}
