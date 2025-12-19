import type {
  DocumentData,
  FirestoreDataConverter,
  QueryDocumentSnapshot,
  SnapshotOptions,
  WithFieldValue,
} from 'firebase/firestore';

export function identityConverter<T>(): FirestoreDataConverter<T> {
  return {
    toFirestore: (value: WithFieldValue<T>) => value as DocumentData,
    fromFirestore: (snapshot: QueryDocumentSnapshot, options: SnapshotOptions) =>
      snapshot.data(options) as T,
  };
}
