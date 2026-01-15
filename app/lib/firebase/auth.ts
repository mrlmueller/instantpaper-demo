import {
  getAuth,
  signInWithPopup,
  GoogleAuthProvider,
  signOut as firebaseSignOut,
  onIdTokenChanged,
  type IdTokenResult,
  type Auth,
  type User,
} from "firebase/auth";
import Cookies from "js-cookie";
import { firebaseApp } from "./config";

let authInstance: Auth | null = null;

export const SESSION_COOKIE_NAME = "__session";

export type AccessState = {
  fullAccess: boolean;
  legacyApproved: boolean;
  blocked: boolean;
};

function isProduction() {
  return process.env.NODE_ENV === "production";
}

export function setSessionCookie(token: string) {
  Cookies.set(SESSION_COOKIE_NAME, token, {
    expires: 14,
    sameSite: "lax",
    secure: isProduction(),
    path: "/",
  });
}

export function clearSessionCookie() {
  Cookies.remove(SESSION_COOKIE_NAME, { path: "/" });
}

function getFirebaseAuth(): Auth {
  if (authInstance) return authInstance;

  // If the Firebase web config is missing, avoid throwing during module evaluation
  // (which would 500 the whole page) and instead fail when auth is actually used.
  const opts = firebaseApp.options as
    | {
        apiKey?: unknown;
        authDomain?: unknown;
        projectId?: unknown;
        appId?: unknown;
      }
    | undefined;
  const missing = [
    ["NEXT_PUBLIC_FIREBASE_API_KEY", opts?.apiKey],
    ["NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN", opts?.authDomain],
    ["NEXT_PUBLIC_FIREBASE_PROJECT_ID", opts?.projectId],
    ["NEXT_PUBLIC_FIREBASE_APP_ID", opts?.appId],
  ]
    .filter(
      ([, value]) => typeof value !== "string" || value.trim().length === 0
    )
    .map(([key]) => key);

  if (missing.length > 0) {
    throw new Error(
      `Firebase ist nicht konfiguriert (${missing.join(
        ", "
      )}). Lege eine .env.local im Projekt-Root an und starte den Dev-Server neu.`
    );
  }

  authInstance = getAuth(firebaseApp);
  return authInstance;
}

export const googleProvider = new GoogleAuthProvider();

// Prompt user to select account every time
googleProvider.setCustomParameters({
  prompt: "select_account",
});

export function parseAccessStateFromClaims(claims: Record<string, unknown> | null | undefined): AccessState {
  const fullAccess = claims?.['fullAccess'] === true;
  const legacyApproved = claims?.['approved'] === true;
  const blocked = claims?.['blocked'] === true;
  return { fullAccess, legacyApproved, blocked };
}

export function hasFullAccess(access: AccessState | null | undefined): boolean {
  return Boolean(access?.fullAccess || access?.legacyApproved);
}

export const signInWithGoogle = async () => {
  try {
    const auth = getFirebaseAuth();
    const result = await signInWithPopup(auth, googleProvider);

    // ID token will be set in cookie by onAuthStateChange listener
    return result.user;
  } catch (error) {
    console.error("Sign in error:", error);
    throw error;
  }
};

export const signOut = async () => {
  try {
    const auth = getFirebaseAuth();
    await firebaseSignOut(auth);
    // Cookie will be deleted by onIdTokenChanged listener
  } catch (error) {
    console.error("Sign out error:", error);
    throw error;
  }
};

export async function getIdTokenResultOrNull(forceRefresh = false): Promise<IdTokenResult | null> {
  try {
    const auth = getFirebaseAuth();
    const user = auth.currentUser;
    if (!user) return null;
    return await user.getIdTokenResult(forceRefresh);
  } catch (error) {
    console.error("Failed to read ID token:", error);
    return null;
  }
}

export async function refreshIdTokenAndCookie(): Promise<{ token: string; access: AccessState } | null> {
  const result = await getIdTokenResultOrNull(true);
  if (!result) return null;
  setSessionCookie(result.token);
  return { token: result.token, access: parseAccessStateFromClaims(result.claims as unknown as Record<string, unknown>) };
}

// Subscribe to auth state changes and keep ID token fresh
export const onAuthStateChange = (callback: (user: User | null, access?: AccessState) => void) => {
  try {
    const auth = getFirebaseAuth();

    return onIdTokenChanged(auth, async (user) => {
      if (user) {
        const idTokenResult = await user.getIdTokenResult();
        const access = parseAccessStateFromClaims(idTokenResult.claims as unknown as Record<string, unknown>);

        // Always store a fresh ID token for server components/actions (cookie is read by Next.js server).
        setSessionCookie(idTokenResult.token);
        callback(user, access);
      } else {
        // User signed out - clean up cookie
        clearSessionCookie();
        callback(null);
      }
    });
  } catch (error) {
    console.error("Firebase auth init failed:", error);
    clearSessionCookie();
    callback(null);
    return () => {};
  }
};
