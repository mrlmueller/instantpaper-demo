import { getFunctions } from "firebase/functions";

import { firebaseApp } from "./config";

const FUNCTIONS_REGION =
  process.env.NEXT_PUBLIC_FIREBASE_FUNCTIONS_REGION || "europe-west3";

export const functionsClient = getFunctions(firebaseApp, FUNCTIONS_REGION);
