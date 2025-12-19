import {
  collection,
  doc,
  type CollectionReference,
  type DocumentReference,
  type Firestore,
} from 'firebase/firestore';
import { identityConverter } from './converters';
import type {
  ArtifactDoc,
  KapitelDoc,
  ProjectDoc,
  QuelleContentDoc,
  QuelleDoc,
  ResultDoc,
  RunDoc,
  SummaryDoc,
  CombinedGroupDoc,
} from './types';

export function userDoc(db: Firestore, uid: string) {
  return doc(db, 'users', uid);
}

export function projectsCol(db: Firestore, uid: string): CollectionReference<ProjectDoc> {
  return collection(db, 'users', uid, 'projects').withConverter(identityConverter<ProjectDoc>());
}

export function projectDoc(db: Firestore, uid: string, projectId: string): DocumentReference<ProjectDoc> {
  return doc(db, 'users', uid, 'projects', projectId).withConverter(identityConverter<ProjectDoc>());
}

export function quellenCol(db: Firestore, uid: string): CollectionReference<QuelleDoc> {
  return collection(db, 'users', uid, 'quellen').withConverter(identityConverter<QuelleDoc>());
}

export function quelleDoc(db: Firestore, uid: string, quelleId: string): DocumentReference<QuelleDoc> {
  return doc(db, 'users', uid, 'quellen', quelleId).withConverter(identityConverter<QuelleDoc>());
}

export function quelleContentDoc(
  db: Firestore,
  uid: string,
  quelleId: string
): DocumentReference<QuelleContentDoc> {
  return doc(db, 'users', uid, 'quellen', quelleId, 'content', 'main').withConverter(
    identityConverter<QuelleContentDoc>()
  );
}

export function kapitelsCol(db: Firestore, uid: string): CollectionReference<KapitelDoc> {
  return collection(db, 'users', uid, 'kapitels').withConverter(identityConverter<KapitelDoc>());
}

export function kapitelDoc(db: Firestore, uid: string, kapitelId: string): DocumentReference<KapitelDoc> {
  return doc(db, 'users', uid, 'kapitels', kapitelId).withConverter(identityConverter<KapitelDoc>());
}

export function runsCol(db: Firestore, uid: string, kapitelId: string): CollectionReference<RunDoc> {
  return collection(db, 'users', uid, 'kapitels', kapitelId, 'runs').withConverter(identityConverter<RunDoc>());
}

export function runDoc(
  db: Firestore,
  uid: string,
  kapitelId: string,
  runId: string
): DocumentReference<RunDoc> {
  return doc(db, 'users', uid, 'kapitels', kapitelId, 'runs', runId).withConverter(identityConverter<RunDoc>());
}

export function resultsCol(
  db: Firestore,
  uid: string,
  kapitelId: string,
  runId: string
): CollectionReference<ResultDoc> {
  return collection(db, 'users', uid, 'kapitels', kapitelId, 'runs', runId, 'results').withConverter(
    identityConverter<ResultDoc>()
  );
}

export function resultDoc(
  db: Firestore,
  uid: string,
  kapitelId: string,
  runId: string,
  quelleId: string
): DocumentReference<ResultDoc> {
  return doc(db, 'users', uid, 'kapitels', kapitelId, 'runs', runId, 'results', quelleId).withConverter(
    identityConverter<ResultDoc>()
  );
}

export function artifactsCol(
  db: Firestore,
  uid: string,
  kapitelId: string,
  runId: string
): CollectionReference<ArtifactDoc> {
  return collection(db, 'users', uid, 'kapitels', kapitelId, 'runs', runId, 'artifacts').withConverter(
    identityConverter<ArtifactDoc>()
  );
}

export function artifactDoc(
  db: Firestore,
  uid: string,
  kapitelId: string,
  runId: string,
  artifactId: 'combined' | 'shortened' | 'lesefluss'
): DocumentReference<ArtifactDoc> {
  return doc(db, 'users', uid, 'kapitels', kapitelId, 'runs', runId, 'artifacts', artifactId).withConverter(
    identityConverter<ArtifactDoc>()
  );
}

export function combinedGroupsCol(
  db: Firestore,
  uid: string,
  kapitelId: string,
  runId: string
): CollectionReference<CombinedGroupDoc> {
  return collection(
    db,
    'users',
    uid,
    'kapitels',
    kapitelId,
    'runs',
    runId,
    'artifacts',
    'combined',
    'groups'
  ).withConverter(identityConverter<CombinedGroupDoc>());
}

export function summariesCol(
  db: Firestore,
  uid: string,
  kapitelId: string,
  runId: string
): CollectionReference<SummaryDoc> {
  return collection(db, 'users', uid, 'kapitels', kapitelId, 'runs', runId, 'summaries').withConverter(
    identityConverter<SummaryDoc>()
  );
}

