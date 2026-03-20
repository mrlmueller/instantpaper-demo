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
  ProjectPdfDoc,
  PdfScanDocSummaryDoc,
  PdfScanResultDoc,
  QuellenFinderRunDoc,
  TwoLaneResultDoc,
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

export function projectPdfsCol(db: Firestore, uid: string, projektId: string): CollectionReference<ProjectPdfDoc> {
  return collection(db, 'users', uid, 'projects', projektId, 'pdfs').withConverter(identityConverter<ProjectPdfDoc>());
}

export function projectPdfDoc(
  db: Firestore,
  uid: string,
  projektId: string,
  pdfId: string
): DocumentReference<ProjectPdfDoc> {
  return doc(db, 'users', uid, 'projects', projektId, 'pdfs', pdfId).withConverter(identityConverter<ProjectPdfDoc>());
}

export function projectResearchRunsCol(
  db: Firestore,
  uid: string,
  projektId: string
): CollectionReference<QuellenFinderRunDoc> {
  return collection(db, 'users', uid, 'projects', projektId, 'researchRuns').withConverter(
    identityConverter<QuellenFinderRunDoc>()
  );
}

export function projectResearchRunDoc(
  db: Firestore,
  uid: string,
  projektId: string,
  runId: string
): DocumentReference<QuellenFinderRunDoc> {
  return doc(db, 'users', uid, 'projects', projektId, 'researchRuns', runId).withConverter(
    identityConverter<QuellenFinderRunDoc>()
  );
}

export function quellenFinderTwoLaneResultsCol(
  db: Firestore,
  uid: string,
  projektId: string,
  runId: string
): CollectionReference<TwoLaneResultDoc> {
  return collection(db, 'users', uid, 'projects', projektId, 'researchRuns', runId, 'twoLaneResults').withConverter(
    identityConverter<TwoLaneResultDoc>()
  );
}

export function quellenFinderTwoLaneTelemetryCol(
  db: Firestore,
  uid: string,
  projektId: string,
  runId: string
): CollectionReference<Record<string, unknown>> {
  return collection(db, 'users', uid, 'projects', projektId, 'researchRuns', runId, 'twoLaneTelemetry').withConverter(
    identityConverter<Record<string, unknown>>()
  );
}

export function quellenFinderTwoLaneTelemetryDoc(
  db: Firestore,
  uid: string,
  projektId: string,
  runId: string,
  docId: string
): DocumentReference<Record<string, unknown>> {
  return doc(db, 'users', uid, 'projects', projektId, 'researchRuns', runId, 'twoLaneTelemetry', docId).withConverter(
    identityConverter<Record<string, unknown>>()
  );
}

export function quellenFinderPdfScanDocsCol(
  db: Firestore,
  uid: string,
  projektId: string,
  runId: string
): CollectionReference<PdfScanDocSummaryDoc> {
  return collection(db, 'users', uid, 'projects', projektId, 'researchRuns', runId, 'pdfScanDocs').withConverter(
    identityConverter<PdfScanDocSummaryDoc>()
  );
}

export function quellenFinderPdfScanSectionsCol(
  db: Firestore,
  uid: string,
  projektId: string,
  runId: string
): CollectionReference<PdfScanResultDoc> {
  return collection(db, 'users', uid, 'projects', projektId, 'researchRuns', runId, 'pdfScanSections').withConverter(
    identityConverter<PdfScanResultDoc>()
  );
}

export function quellenFinderPdfStage2Col(
  db: Firestore,
  uid: string,
  projektId: string,
  runId: string
): CollectionReference<PdfScanDocSummaryDoc> {
  return quellenFinderPdfScanDocsCol(db, uid, projektId, runId);
}

export function quellenFinderPdfStage3Col(
  db: Firestore,
  uid: string,
  projektId: string,
  runId: string
): CollectionReference<PdfScanResultDoc> {
  return quellenFinderPdfScanSectionsCol(db, uid, projektId, runId);
}

