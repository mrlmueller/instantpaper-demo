import { initializeServerApp } from 'firebase/app';
import { getAuth } from 'firebase/auth';
import { getFirestore } from 'firebase/firestore';
import { cookies } from 'next/headers';
import { firebaseApp } from './config';

export async function getAuthenticatedAppForUser() {
  const cookieStore = await cookies();
  const authIdToken = cookieStore.get('__session')?.value;

  const firebaseServerApp = initializeServerApp(
    firebaseApp.options,
    authIdToken ? { authIdToken } : {}
  );

  const auth = getAuth(firebaseServerApp);
  await auth.authStateReady();

  return { firebaseServerApp, currentUser: auth.currentUser };
}

export async function getFirestoreForUser() {
  const { firebaseServerApp } = await getAuthenticatedAppForUser();
  return getFirestore(firebaseServerApp);
}
