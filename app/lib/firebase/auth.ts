import {
  getAuth,
  signInWithPopup,
  GoogleAuthProvider,
  signOut as firebaseSignOut,
  onIdTokenChanged,
  type User,
} from 'firebase/auth';
import Cookies from 'js-cookie';
import { firebaseApp } from './config';

export const auth = getAuth(firebaseApp);

export const googleProvider = new GoogleAuthProvider();

// Prompt user to select account every time
googleProvider.setCustomParameters({
  prompt: 'select_account',
});

export const signInWithGoogle = async () => {
  try {
    const result = await signInWithPopup(auth, googleProvider);

    // ID token will be set in cookie by onAuthStateChange listener
    return result.user;
  } catch (error) {
    console.error('Sign in error:', error);
    throw error;
  }
};

export const signOut = async () => {
  try {
    await firebaseSignOut(auth);
    // Cookie will be deleted by onIdTokenChanged listener
  } catch (error) {
    console.error('Sign out error:', error);
    throw error;
  }
};

// Subscribe to auth state changes and keep ID token fresh
export const onAuthStateChange = (callback: (user: User | null) => void) => {
  return onIdTokenChanged(auth, async (user) => {
    if (user) {
      // User is signed in - store fresh ID token
      const idToken = await user.getIdToken();
      Cookies.set('__session', idToken, {
        expires: 14, // Cookie lasts 14 days, but token auto-refreshes
        sameSite: 'lax',
        secure: process.env.NODE_ENV === 'production'
      });
    } else {
      // User signed out - clean up cookie
      Cookies.remove('__session');
    }
    callback(user);
  });
};
