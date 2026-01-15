import { addDoc, collection, onSnapshot } from "firebase/firestore";

import { firestoreClient } from "./firestoreClient";

export type StripeCheckoutMode = "subscription" | "payment";

const FALLBACK_SUBSCRIPTION_PRICE_ID = "price_1SpqOYDXfswW2xixZsMQLjUI";
const FALLBACK_TOPUP_PRICE_ID = "price_1SpqTADXfswW2xixLU9G63O6";

export const STRIPE_SUBSCRIPTION_PRICE_ID =
  process.env.NEXT_PUBLIC_STRIPE_SUBSCRIPTION_PRICE_ID ||
  FALLBACK_SUBSCRIPTION_PRICE_ID;
export const STRIPE_TOPUP_PRICE_ID =
  process.env.NEXT_PUBLIC_STRIPE_TOPUP_PRICE_ID || FALLBACK_TOPUP_PRICE_ID;

type StripeCheckoutSessionDoc = {
  url?: unknown;
  error?: unknown;
};

function asNonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function extractCheckoutErrorMessage(errorValue: unknown): string {
  const asString = asNonEmptyString(errorValue);
  if (asString) return asString;

  if (errorValue && typeof errorValue === "object") {
    const maybeMessage = asNonEmptyString((errorValue as { message?: unknown }).message);
    if (maybeMessage) return maybeMessage;
  }

  return "Checkout konnte nicht gestartet werden.";
}

export async function createCheckoutSessionUrl(params: {
  uid: string;
  mode: StripeCheckoutMode;
  priceId: string;
  successUrl: string;
  cancelUrl: string;
}): Promise<string> {
  const uid = asNonEmptyString(params.uid);
  if (!uid) throw new Error("Nicht eingeloggt.");

  const priceId = asNonEmptyString(params.priceId);
  if (!priceId) throw new Error("Stripe Price ID fehlt.");

  const successUrl = asNonEmptyString(params.successUrl);
  const cancelUrl = asNonEmptyString(params.cancelUrl);
  if (!successUrl || !cancelUrl) throw new Error("Checkout Redirect URLs fehlen.");

  const checkoutSessionsRef = collection(
    firestoreClient,
    "customers",
    uid,
    "checkout_sessions"
  );

  const docRef = await addDoc(checkoutSessionsRef, {
    mode: params.mode,
    price: priceId,
    success_url: successUrl,
    cancel_url: cancelUrl,
  });

  return await new Promise<string>((resolve, reject) => {
    let unsub = () => {};
    const timeout = setTimeout(() => {
      unsub();
      reject(new Error("Checkout timed out. Bitte versuche es erneut."));
    }, 30_000);

    unsub = onSnapshot(
      docRef,
      (snap) => {
        const data = (snap.data() || {}) as StripeCheckoutSessionDoc;
        const errorMessage = data.error ? extractCheckoutErrorMessage(data.error) : null;
        if (errorMessage) {
          clearTimeout(timeout);
          unsub();
          reject(new Error(errorMessage));
          return;
        }

        const url = asNonEmptyString(data.url);
        if (url) {
          clearTimeout(timeout);
          unsub();
          resolve(url);
        }
      },
      (err) => {
        clearTimeout(timeout);
        unsub();
        reject(err);
      }
    );
  });
}
