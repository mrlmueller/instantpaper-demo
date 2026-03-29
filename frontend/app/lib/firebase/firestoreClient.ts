import { getFirestore } from 'firebase/firestore';
import { firebaseApp } from './config';

export const firestoreClient = getFirestore(firebaseApp);
