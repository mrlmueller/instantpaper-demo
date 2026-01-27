const functions = require("firebase-functions");
const admin = require("firebase-admin");

admin.initializeApp();

const db = admin.firestore();

const DEFAULT_CREDITS_CONFIG = Object.freeze({
  purchaseCreditsPerUsd: 3,
  subscriptionBonusCredits: 10,
  subscriptionCreditsPerPeriod: 85,
  topupPriceId: "price_1SpqTADXfswW2xixLU9G63O6",
  subscriptionPriceId: "price_1SpqOYDXfswW2xixZsMQLjUI",
});

let cachedCreditsConfig = null;
let cachedCreditsConfigAtMs = 0;

async function getCreditsConfig() {
  const now = Date.now();
  if (cachedCreditsConfig && now - cachedCreditsConfigAtMs < 60_000) {
    return cachedCreditsConfig;
  }

  try {
    const snap = await db.collection("_config").doc("credits").get();
    const data = snap.exists ? snap.data() || {} : {};
    cachedCreditsConfig = {
      purchaseCreditsPerUsd:
        typeof data.purchaseCreditsPerUsd === "number"
          ? data.purchaseCreditsPerUsd
          : DEFAULT_CREDITS_CONFIG.purchaseCreditsPerUsd,
      subscriptionBonusCredits:
        typeof data.subscriptionBonusCredits === "number"
          ? data.subscriptionBonusCredits
          : DEFAULT_CREDITS_CONFIG.subscriptionBonusCredits,
      subscriptionCreditsPerPeriod:
        typeof data.subscriptionCreditsPerPeriod === "number"
          ? data.subscriptionCreditsPerPeriod
          : DEFAULT_CREDITS_CONFIG.subscriptionCreditsPerPeriod,
      topupPriceId:
        typeof data.topupPriceId === "string" && data.topupPriceId.trim()
          ? data.topupPriceId.trim()
          : DEFAULT_CREDITS_CONFIG.topupPriceId,
      subscriptionPriceId:
        typeof data.subscriptionPriceId === "string" && data.subscriptionPriceId.trim()
          ? data.subscriptionPriceId.trim()
          : DEFAULT_CREDITS_CONFIG.subscriptionPriceId,
    };
    cachedCreditsConfigAtMs = now;
    return cachedCreditsConfig;
  } catch (err) {
    cachedCreditsConfig = DEFAULT_CREDITS_CONFIG;
    cachedCreditsConfigAtMs = now;
    return cachedCreditsConfig;
  }
}

function isSuccessfulPayment(data) {
  const status = String(data?.status || "").trim().toLowerCase();
  if (status === "succeeded" || status === "paid") return true;
  if (data?.paid === true) return true;
  return false;
}

function toNumberOrNull(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const n = Number(value.trim());
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function centsToUsd(cents) {
  const n = toNumberOrNull(cents);
  if (n === null) return null;
  return n / 100;
}

function toFirestoreTimestamp(value) {
  if (!value) return null;
  if (value instanceof admin.firestore.Timestamp) return value;

  const asNumber = toNumberOrNull(value);
  if (asNumber !== null) {
    // Stripe timestamps are usually seconds; sometimes ms.
    const ms = asNumber > 1e12 ? asNumber : asNumber * 1000;
    return admin.firestore.Timestamp.fromMillis(ms);
  }

  if (typeof value === "object") {
    const seconds = toNumberOrNull(value.seconds);
    const nanos = toNumberOrNull(value.nanoseconds);
    if (seconds !== null) {
      return new admin.firestore.Timestamp(seconds, nanos ? nanos : 0);
    }
  }

  return null;
}

function collectPriceIds(data) {
  const out = new Set();

  const pushId = (candidate) => {
    if (typeof candidate === "string" && candidate.trim()) out.add(candidate.trim());
  };

  pushId(data?.price);
  pushId(data?.priceId);
  pushId(data?.price_id);
  pushId(data?.line_items?.data?.[0]?.price?.id);
  pushId(data?.line_items?.data?.[0]?.price);

  const items = Array.isArray(data?.items) ? data.items : [];
  for (const item of items) {
    pushId(item?.price?.id);
    pushId(item?.price);
    pushId(item?.priceId);
  }

  const prices = Array.isArray(data?.prices) ? data.prices : [];
  for (const p of prices) {
    pushId(p?.id);
    pushId(p);
  }

  const metadata = data?.metadata && typeof data.metadata === "object" ? data.metadata : {};
  pushId(metadata?.priceId);
  pushId(metadata?.price_id);

  return out;
}

async function upsertActivationFromPayment(uid, opts) {
  const uidNorm = String(uid || "").trim();
  if (!uidNorm) return { blocked: false, alreadyActive: false };

  const userRef = db.collection("users").doc(uidNorm);
  const userSnap = await userRef.get();
  const userData = userSnap.exists ? userSnap.data() || {} : {};
  const status = String(userData.accountStatus || "").trim().toLowerCase();
  const blocked = status === "blocked";

  // Never auto-unblock.
  if (!blocked) {
    let authUser = null;
    try {
      authUser = await admin.auth().getUser(uidNorm);
    } catch {
      authUser = null;
    }

    const payload = {
      uid: uidNorm,
      email: authUser?.email || userData.email || null,
      displayName: authUser?.displayName || userData.displayName || null,
      photoURL: authUser?.photoURL || userData.photoURL || null,
      accountStatus: status || "active",
      activatedAt: userData.activatedAt || admin.firestore.FieldValue.serverTimestamp(),
      activatedByCode: userData.activatedByCode || null,
      activatedByPayment: opts?.paymentId || opts?.subscriptionId || "stripe",
      updatedAt: admin.firestore.FieldValue.serverTimestamp(),
    };

    if (!userSnap.exists) {
      payload.createdAt = admin.firestore.FieldValue.serverTimestamp();
    }

    await userRef.set(payload, { merge: true });
  }

  // Only set access claims if not blocked.
  if (!blocked) {
    try {
      const authUser = await admin.auth().getUser(uidNorm);
      const existing = authUser.customClaims || {};
      if (existing.fullAccess === true || existing.approved === true) {
        return { blocked: false, alreadyActive: true };
      }

      const nextClaims = { ...existing, fullAccess: true };
      delete nextClaims.approved;
      await admin.auth().setCustomUserClaims(uidNorm, nextClaims);
    } catch {
      // Ignore auth failures; user can still be activated via admin/code.
    }
  }

  return { blocked, alreadyActive: false };
}

exports.onStripePaymentWrite = functions.firestore
  .document("customers/{uid}/payments/{paymentId}")
  .onWrite(async (change, context) => {
    const uid = String(context.params.uid || "").trim();
    const paymentId = String(context.params.paymentId || "").trim();
    if (!uid || !paymentId) return;

    if (!change.after.exists) return;
    const data = change.after.data() || {};

    if (!isSuccessfulPayment(data)) return;

    const cfg = await getCreditsConfig();

    const invoiceCandidate = data?.invoice || data?.invoiceId || data?.invoice_id;
    const invoiceId =
      typeof invoiceCandidate === "string"
        ? invoiceCandidate.trim()
        : invoiceCandidate
        ? String(invoiceCandidate).trim()
        : "";

    // Subscription payments are invoice-based; avoid double-granting by ignoring invoice payments here.
    if (invoiceId) return;

    const priceIds = collectPriceIds(data);

    // Stripe PaymentIntents often don't carry price IDs; treat successful non-invoice payments as top-ups.
    const isTopup = priceIds.size ? priceIds.has(cfg.topupPriceId) : true;
    if (!isTopup) return;

    const amountUsd =
      centsToUsd(data.amount_received) ??
      centsToUsd(data.amount_total) ??
      centsToUsd(data.amount) ??
      null;
    if (amountUsd === null) return;

    const credits = Number(amountUsd) * Number(cfg.purchaseCreditsPerUsd || 0);
    if (!Number.isFinite(credits) || credits === 0) return;

    const ledgerId = `stripe_topup_${paymentId}`;
    const ledgerRef = db.collection("users").doc(uid).collection("creditLedger").doc(ledgerId);
    const balanceRef = db.collection("users").doc(uid).collection("billing").doc("balance");

    await db.runTransaction(async (tx) => {
      const existingLedger = await tx.get(ledgerRef);
      if (existingLedger.exists) return;

      const balanceSnap = await tx.get(balanceRef);
      const balance = balanceSnap.exists ? balanceSnap.data() || {} : {};
      const topupCredits = toNumberOrNull(balance.topupCredits) ?? 0;

      tx.set(
        balanceRef,
        {
          topupCredits: topupCredits + credits,
          updatedAt: admin.firestore.FieldValue.serverTimestamp(),
        },
        { merge: true }
      );

      tx.set(ledgerRef, {
        type: "grant",
        source: "stripe_topup",
        credits,
        createdAt: admin.firestore.FieldValue.serverTimestamp(),
        expiresAt: null,
        stripe: {
          paymentId,
          priceIds: Array.from(priceIds),
          amountUsd,
          currency: String(data.currency || "usd"),
        },
      });
    });

    await upsertActivationFromPayment(uid, { paymentId });
  });

exports.onStripeSubscriptionWrite = functions.firestore
  .document("customers/{uid}/subscriptions/{subscriptionId}")
  .onWrite(async (change, context) => {
    const uid = String(context.params.uid || "").trim();
    const subscriptionId = String(context.params.subscriptionId || "").trim();
    if (!uid || !subscriptionId) return;

    if (!change.after.exists) return;
    const data = change.after.data() || {};

    const status = String(data.status || "").trim().toLowerCase();
    const isActive = status === "active" || status === "trialing";
    if (!isActive) return;

    const periodEnd = toFirestoreTimestamp(data.current_period_end);
    if (!periodEnd) return;

    const periodEndSeconds = String(periodEnd.seconds);
    const ledgerId = `stripe_subscription_${subscriptionId}_${periodEndSeconds}`;

    const cfg = await getCreditsConfig();
    const credits = Number(cfg.subscriptionCreditsPerPeriod || 0);
    if (!Number.isFinite(credits) || credits === 0) return;

    const ledgerRef = db.collection("users").doc(uid).collection("creditLedger").doc(ledgerId);
    const balanceRef = db.collection("users").doc(uid).collection("billing").doc("balance");

    await db.runTransaction(async (tx) => {
      const existingLedger = await tx.get(ledgerRef);
      if (existingLedger.exists) return;

      tx.set(
        balanceRef,
        {
          subscriptionCredits: credits,
          subscriptionExpiresAt: periodEnd,
          updatedAt: admin.firestore.FieldValue.serverTimestamp(),
        },
        { merge: true }
      );

      tx.set(ledgerRef, {
        type: "grant",
        source: "stripe_subscription",
        credits,
        createdAt: admin.firestore.FieldValue.serverTimestamp(),
        expiresAt: periodEnd,
        stripe: {
          subscriptionId,
          status,
          currentPeriodEnd: periodEnd,
        },
      });
    });

    await upsertActivationFromPayment(uid, { subscriptionId });
  });

// ---------------------------------------------------------------------------
// Project deletion (admin-only via callable function)
// ---------------------------------------------------------------------------

const PROJECT_DELETE_REGION = "europe-west3";
const DEFAULT_PROJECT_ID = "default";

function normalizeProjectName(value) {
  return String(value || "")
    .normalize("NFKC")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase();
}

async function recursiveDeleteByProjektId({ uid, projektId, collectionName, bulkWriter }) {
  const colRef = db.collection("users").doc(uid).collection(collectionName);
  const snap = await colRef.where("projektId", "==", projektId).get();
  for (const docSnap of snap.docs) {
    await db.recursiveDelete(docSnap.ref, bulkWriter);
  }
}

exports.deleteProjectPermanently = functions
  .region(PROJECT_DELETE_REGION)
  .runWith({ timeoutSeconds: 540, memory: "1GB" })
  .https.onCall(async (data, context) => {
    try {
      const uid = String(context?.auth?.uid || "").trim();
      if (!uid) return { success: false, error: "Nicht eingeloggt." };

      const projectId = typeof data?.projectId === "string" ? data.projectId.trim() : "";
      const confirmName = typeof data?.confirmName === "string" ? data.confirmName : "";

      if (!projectId) return { success: false, error: "Projekt-ID fehlt." };
      if (projectId === DEFAULT_PROJECT_ID) {
        return { success: false, error: "Standardprojekt kann nicht gelöscht werden." };
      }

      const projectRef = db.collection("users").doc(uid).collection("projects").doc(projectId);
      const projectSnap = await projectRef.get();
      if (!projectSnap.exists) return { success: false, error: "Projekt nicht gefunden." };

      const projectData = projectSnap.data() || {};
      const ownerId = typeof projectData.ownerId === "string" ? projectData.ownerId : uid;
      if (ownerId !== uid) return { success: false, error: "Keine Berechtigung." };

      const expectedName = typeof projectData.name === "string" ? projectData.name : "";
      if (!expectedName) return { success: false, error: "Projektname fehlt." };

      if (normalizeProjectName(confirmName) !== normalizeProjectName(expectedName)) {
        return { success: false, error: "Projektname stimmt nicht überein." };
      }

      const bulkWriter = db.bulkWriter();
      bulkWriter.onWriteError((err) => {
        console.error("BulkWriter error (deleteProjectPermanently):", err);
        return err.failedAttempts < 5;
      });

      // Delete related documents first (those reference projektId).
      await recursiveDeleteByProjektId({ uid, projektId: projectId, collectionName: "gliederungDrafts", bulkWriter });
      await recursiveDeleteByProjektId({ uid, projektId: projectId, collectionName: "quellen", bulkWriter });
      await recursiveDeleteByProjektId({ uid, projektId: projectId, collectionName: "kapitels", bulkWriter });

      // Finally delete the project itself.
      await db.recursiveDelete(projectRef, bulkWriter);

      await bulkWriter.close();

      return { success: true };
    } catch (err) {
      console.error("deleteProjectPermanently failed:", err);
      return { success: false, error: "Interner Fehler beim Löschen." };
    }
  });
