import {
  getAuth,
  signInWithPopup,
  GoogleAuthProvider,
  signOut as firebaseSignOut,
  onIdTokenChanged,
  type Auth,
  type User,
} from "firebase/auth";
import Cookies from "js-cookie";
import { firebaseApp } from "./config";

let authInstance: Auth | null = null;

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

// Subscribe to auth state changes and keep ID token fresh
export const onAuthStateChange = (callback: (user: User | null) => void) => {
  try {
    const auth = getFirebaseAuth();

    return onIdTokenChanged(auth, async (user) => {
      if (user) {
        let idTokenResult = await user.getIdTokenResult();
        let approved = Boolean((idTokenResult.claims as any)?.approved === true);

        // If the user was just approved, the current token can still be stale.
        // Only force-refresh when needed to avoid an infinite refresh loop.
        if (!approved) {
          idTokenResult = await user.getIdTokenResult(true);
          approved = Boolean((idTokenResult.claims as any)?.approved === true);
        }

        // Not approved -> immediately sign out and clear cookie.
        if (!approved) {
          Cookies.remove("__session");
          try {
            await firebaseSignOut(auth);
          } catch (err) {
            console.error("Sign out after unauthorized login failed:", err);
          }
          callback(null);
          return;
        }

        // Approved user: store fresh ID token for server components (cookie is read by Next.js server).
        Cookies.set("__session", idTokenResult.token, {
          expires: 14, // Cookie lasts 14 days, but token auto-refreshes
          sameSite: "lax",
          secure: process.env.NODE_ENV === "production",
        });
      } else {
        // User signed out - clean up cookie
        Cookies.remove("__session");
      }
      callback(user);
    });
  } catch (error) {
    console.error("Firebase auth init failed:", error);
    Cookies.remove("__session");
    callback(null);
    return () => {};
  }
};
