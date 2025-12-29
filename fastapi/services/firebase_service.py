import firebase_admin
from firebase_admin import credentials, auth, firestore
from google.cloud.firestore_v1 import SERVER_TIMESTAMP, Increment
from utils.config import config
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

AI_GENERIC_ERROR_MESSAGE = "Fehler bei der Verarbeitung. Wenn es weiterhin passiert, bitte melde dich."


class FirebaseService:
    """Service for Firebase Admin SDK operations"""

    _instance = None
    _initialized = False
    _db = None

    def __new__(cls):
        """Singleton pattern to ensure only one Firebase instance"""
        if cls._instance is None:
            cls._instance = super(FirebaseService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Constructor - does not initialize Firebase yet (lazy initialization)"""
        pass

    def _ensure_initialized(self):
        """Lazy initialization - only initialize when actually needed"""
        if not self._initialized:
            try:
                # Check if credentials are configured
                if not config.FIREBASE_PRIVATE_KEY or config.FIREBASE_PRIVATE_KEY == '':
                    raise ValueError(
                        "Firebase credentials not configured. Please add your Firebase Admin SDK "
                        "credentials to the .env file. Get them from: "
                        "Firebase Console > Project Settings > Service Accounts > Generate New Private Key"
                    )

                # Create credentials from config
                cred_dict = {
                    "type": "service_account",
                    "project_id": config.FIREBASE_PROJECT_ID,
                    "private_key": config.FIREBASE_PRIVATE_KEY.replace('\\n', '\n'),
                    "client_email": config.FIREBASE_CLIENT_EMAIL,
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                }

                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)

                # Initialize Firestore client
                self._db = firestore.client()

                self._initialized = True
                logger.info("Firebase Admin SDK initialized successfully")

            except Exception as e:
                logger.error(f"Failed to initialize Firebase Admin SDK: {str(e)}")
                raise

    @property
    def db(self):
        """Get Firestore client, initializing Firebase if needed"""
        self._ensure_initialized()
        return self._db

    async def verify_token(self, token: str) -> dict:
        """
        Verify Firebase ID token and return decoded token

        Args:
            token: Firebase ID token from Authorization header

        Returns:
            dict: Decoded token with user information

        Raises:
            Exception: If token verification fails
        """
        try:
            # Ensure Firebase is initialized before verifying token
            self._ensure_initialized()
            decoded_token = auth.verify_id_token(token)
            return decoded_token
        except Exception as e:
            logger.error(f"Token verification failed: {str(e)}")
            raise

    async def create_session_cookie(self, id_token: str, expires_in_days: int = 14) -> str:
        """
        Create a Firebase session cookie from an ID token.

        Args:
            id_token: Valid Firebase ID token
            expires_in_days: Session duration (max 14 days)

        Returns:
            str: Session cookie string

        Raises:
            Exception: If session cookie creation fails
        """
        from datetime import timedelta

        try:
            self._ensure_initialized()
            expires_in = timedelta(days=expires_in_days)
            session_cookie = auth.create_session_cookie(id_token, expires_in=expires_in)
            logger.info(f"Created session cookie with {expires_in_days} days expiration")
            return session_cookie
        except Exception as e:
            logger.error(f"Session cookie creation failed: {str(e)}")
            raise

    async def verify_session_cookie(self, session_cookie: str, check_revoked: bool = True) -> dict:
        """
        Verify a Firebase session cookie.

        Args:
            session_cookie: Session cookie to verify
            check_revoked: Whether to check if token was revoked

        Returns:
            dict: Decoded token with user information

        Raises:
            Exception: If verification fails
        """
        try:
            self._ensure_initialized()
            decoded_token = auth.verify_session_cookie(session_cookie, check_revoked=check_revoked)
            return decoded_token
        except Exception as e:
            logger.error(f"Session cookie verification failed: {str(e)}")
            raise

    async def set_user_approved_by_email(self, email: str, approved: bool) -> dict:
        """
        Set the Firebase Auth custom claim `approved` for a user identified by email.

        Note: custom claims are embedded into ID tokens; users must refresh/re-login to receive updates.
        """
        self._ensure_initialized()
        email_norm = (email or "").strip()
        if not email_norm:
            raise ValueError("email is required")

        try:
            user = auth.get_user_by_email(email_norm)
        except auth.UserNotFoundError as exc:
            raise ValueError("User not found. Ask the user to sign in once, then approve again.") from exc
        existing_claims = user.custom_claims or {}
        next_claims = {**existing_claims, "approved": bool(approved)}
        auth.set_custom_user_claims(user.uid, next_claims)

        return {
            "uid": user.uid,
            "email": user.email,
            "approved": bool(approved),
            "customClaims": next_claims,
        }

    async def get_quelle_meta(self, user_id: str, quelle_id: str) -> Optional[dict]:
        """Fetch a Quelle metadata doc (`users/{uid}/quellen/{quelleId}`)."""
        try:
            doc_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("quellen")
                .document(quelle_id)
            )
            doc = doc_ref.get()
            if not doc.exists:
                logger.warning(f"Quelle {quelle_id} not found for user {user_id}")
                return None
            data = doc.to_dict() or {}
            data["id"] = doc.id
            return data
        except Exception as e:
            logger.error(f"Error fetching Quelle meta: {str(e)}")
            raise

    async def get_quelle_content(self, user_id: str, quelle_id: str) -> Optional[dict]:
        """Fetch Quelle content doc (`users/{uid}/quellen/{quelleId}/content/main`)."""
        try:
            doc_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("quellen")
                .document(quelle_id)
                .collection("content")
                .document("main")
            )
            doc = doc_ref.get()
            if not doc.exists:
                logger.warning(f"Quelle content missing for quelle {quelle_id} user {user_id}")
                return None
            data = doc.to_dict() or {}
            data["id"] = doc.id
            return data
        except Exception as e:
            logger.error(f"Error fetching Quelle content: {str(e)}")
            raise

    async def get_quelle(self, user_id: str, quelle_id: str) -> Optional[dict]:
        """Backward-compat alias for Quelle metadata (V2 stores content separately)."""
        return await self.get_quelle_meta(user_id, quelle_id)

    async def save_result(
        self,
        user_id: str,
        quelle_id: str,
        kapitel_id: str,
        run_id: str,
        result_content: str,
        has_content: bool,
        model_used: str,
        tokens_used: int,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int,
        cost: float,
        key_source: Optional[str] = None,
    ) -> str:
        """
        Save AI processing result to Firestore under a Kapitel run

        Args:
            user_id: User ID
            quelle_id: Source Quelle ID
            kapitel_id: Kapitel ID that initiated the run
            run_id: Run ID for grouping this result
            result_content: AI-generated content
            model_used: OpenAI model used
            tokens_used: Total number of tokens consumed
            input_tokens: Number of input tokens consumed
            cached_input_tokens: Number of cached input tokens (charged at 10% rate)
            output_tokens: Number of output tokens consumed (visible)
            reasoning_tokens: Number of reasoning tokens consumed (internal chain-of-thought)
            cost: Cost in USD for this processing

        Returns:
            str: Result document ID
        """
        try:
            if not kapitel_id or not run_id:
                raise ValueError("kapitel_id and run_id are required to save results")

            # Create result document in nested runs collection
            result_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('results')
                .document(quelle_id)
            )

            existing = result_ref.get()
            existing_data = existing.to_dict() if existing.exists else {}
            is_new = not existing.exists

            created_at_value = existing_data.get("createdAt") if existing.exists else SERVER_TIMESTAMP
            started_at_value = (
                existing_data.get("startedAt")
                if existing.exists and existing_data.get("startedAt") is not None
                else created_at_value
            )
            existing_refinement = existing_data.get("refinement") if isinstance(existing_data, dict) else None
            refinement_value = (
                existing_refinement
                if isinstance(existing_refinement, dict) and existing_refinement.get("rootVersionId") == "root"
                else {
                    "rootVersionId": "root",
                    "activeVersionId": "root",
                    "maxDepth": int(config.TEXT_REFINEMENT_MAX_DEPTH),
                    "costTotalUsd": 0.0,
                    "initializedAt": SERVER_TIMESTAMP,
                }
            )

            status_value = (
                "success"
                if bool(has_content) and (result_content or "").strip()
                else "no-content"
            )

            result_data = {
                "quelleId": quelle_id,
                "userInput": "",
                "content": result_content,
                "hasContent": bool(has_content),
                "status": status_value,
                "errorMessage": None,
                "errorAt": None,
                "model": model_used,
                "usage": {
                    "inputTokens": int(input_tokens),
                    "cachedInputTokens": int(cached_input_tokens),
                    "outputTokens": int(output_tokens),
                    "reasoningTokens": int(reasoning_tokens),
                    "totalTokens": int(tokens_used),
                },
                "costUsd": float(cost),
                "keySource": key_source,
                "createdAt": created_at_value,
                "startedAt": started_at_value,
                "updatedAt": SERVER_TIMESTAMP,
                "finishedAt": SERVER_TIMESTAMP,
                "refinement": refinement_value,
            }

            batch = self.db.batch()
            # Always write the V2 shape; preserve createdAt + refinement when re-saving.
            batch.set(result_ref, result_data)

            run_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("kapitels")
                .document(kapitel_id)
                .collection("runs")
                .document(run_id)
            )
            run_update: dict = {
                "lastResultAt": SERVER_TIMESTAMP,
                "lastActivityAt": SERVER_TIMESTAMP,
                "updatedAt": SERVER_TIMESTAMP,
            }
            prev_status = existing_data.get("status") if isinstance(existing_data, dict) else None
            should_count_completion = is_new or prev_status == "running"
            if should_count_completion:
                run_update["resultsCompletedCount"] = Increment(1)
                if bool(has_content) and (result_content or "").strip():
                    run_update["resultsWithContentCount"] = Increment(1)
            batch.set(run_ref, run_update, merge=True)

            batch.commit()
            logger.info(
                f"Saved result for quelle {quelle_id} in kapitel {kapitel_id} run {run_id} for user {user_id} "
                f"(cost: ${cost:.6f}, cached: {cached_input_tokens}, reasoning: {reasoning_tokens})"
            )

            return result_ref.id

        except Exception as e:
            logger.error(f"Error saving result: {str(e)}")
            raise

    def _run_result_ref(self, user_id: str, kapitel_id: str, run_id: str, quelle_id: str):
        return (
            self.db.collection('users')
            .document(user_id)
            .collection('kapitels')
            .document(kapitel_id)
            .collection('runs')
            .document(run_id)
            .collection('results')
            .document(quelle_id)
        )

    async def mark_result_running(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        quelle_id: str,
        model: str,
        key_source: Optional[str] = None,
    ) -> None:
        """
        Create/merge a placeholder result doc (status=running) so the UI can show progress and avoid infinite spinners.
        """
        try:
            result_ref = self._run_result_ref(user_id, kapitel_id, run_id, quelle_id)
            existing = result_ref.get()
            existing_data = existing.to_dict() if existing.exists else {}

            created_at_value = existing_data.get("createdAt") if existing.exists else SERVER_TIMESTAMP
            started_at_value = (
                existing_data.get("startedAt")
                if existing.exists and existing_data.get("startedAt") is not None
                else SERVER_TIMESTAMP
            )

            existing_refinement = existing_data.get("refinement") if isinstance(existing_data, dict) else None
            refinement_value = (
                existing_refinement
                if isinstance(existing_refinement, dict) and existing_refinement.get("rootVersionId") == "root"
                else {
                    "rootVersionId": "root",
                    "activeVersionId": "root",
                    "maxDepth": int(config.TEXT_REFINEMENT_MAX_DEPTH),
                    "costTotalUsd": 0.0,
                    "initializedAt": SERVER_TIMESTAMP,
                }
            )

            placeholder = {
                "quelleId": quelle_id,
                "userInput": "",
                "content": "",
                "hasContent": True,
                "status": "running",
                "errorMessage": None,
                "errorAt": None,
                "model": model or "",
                "usage": {
                    "inputTokens": 0,
                    "cachedInputTokens": 0,
                    "outputTokens": 0,
                    "reasoningTokens": 0,
                    "totalTokens": 0,
                },
                "costUsd": 0.0,
                "keySource": key_source,
                "createdAt": created_at_value,
                "startedAt": started_at_value,
                "updatedAt": SERVER_TIMESTAMP,
                "finishedAt": None,
                "refinement": refinement_value,
            }

            batch = self.db.batch()
            batch.set(result_ref, placeholder, merge=True)

            run_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("kapitels")
                .document(kapitel_id)
                .collection("runs")
                .document(run_id)
            )
            batch.set(
                run_ref,
                {"lastActivityAt": SERVER_TIMESTAMP, "updatedAt": SERVER_TIMESTAMP},
                merge=True,
            )
            batch.commit()
        except Exception as e:
            logger.error(f"Error marking result running: {e}")

    async def mark_result_error(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        quelle_id: str,
        *,
        key_source: Optional[str] = None,
    ) -> None:
        """Mark a result doc as errored (status=error) with a generic message."""
        try:
            result_ref = self._run_result_ref(user_id, kapitel_id, run_id, quelle_id)
            existing = result_ref.get()
            existing_data = existing.to_dict() if existing.exists else {}

            created_at_value = existing_data.get("createdAt") if existing.exists else SERVER_TIMESTAMP
            started_at_value = (
                existing_data.get("startedAt")
                if existing.exists and existing_data.get("startedAt") is not None
                else SERVER_TIMESTAMP
            )

            prev_status = existing_data.get("status") if isinstance(existing_data, dict) else None
            should_count_completion = (not existing.exists) or prev_status == "running"

            update = {
                "quelleId": quelle_id,
                "content": "",
                "hasContent": True,
                "status": "error",
                "errorMessage": AI_GENERIC_ERROR_MESSAGE,
                "errorAt": SERVER_TIMESTAMP,
                "keySource": key_source,
                "createdAt": created_at_value,
                "startedAt": started_at_value,
                "updatedAt": SERVER_TIMESTAMP,
                "finishedAt": SERVER_TIMESTAMP,
            }

            batch = self.db.batch()
            batch.set(result_ref, update, merge=True)

            run_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("kapitels")
                .document(kapitel_id)
                .collection("runs")
                .document(run_id)
            )
            run_update: dict = {"lastActivityAt": SERVER_TIMESTAMP, "updatedAt": SERVER_TIMESTAMP}
            if should_count_completion:
                run_update["resultsCompletedCount"] = Increment(1)
            batch.set(run_ref, run_update, merge=True)
            batch.commit()
        except Exception as e:
            logger.error(f"Error marking result error: {e}")

    def _run_result_refinement_version_ref(
        self, user_id: str, kapitel_id: str, run_id: str, quelle_id: str, version_id: str
    ):
        return self._run_result_ref(user_id, kapitel_id, run_id, quelle_id).collection('versions').document(version_id)

    async def get_run_result(
        self, user_id: str, kapitel_id: str, run_id: str, quelle_id: str
    ) -> Optional[dict]:
        """Fetch a single result doc under runs/{runId}/results/{quelleId}."""
        try:
            doc_ref = self._run_result_ref(user_id, kapitel_id, run_id, quelle_id)
            doc = doc_ref.get()
            if not doc.exists:
                return None
            data = doc.to_dict() or {}
            data['id'] = doc.id
            return data
        except Exception as e:
            logger.error(f"Error fetching run result {quelle_id} for run {run_id}: {str(e)}")
            raise

    async def get_result_refinement_version(
        self, user_id: str, kapitel_id: str, run_id: str, quelle_id: str, version_id: str
    ) -> Optional[dict]:
        """Fetch a per-result refinement version (if it exists)."""
        try:
            doc_ref = self._run_result_refinement_version_ref(user_id, kapitel_id, run_id, quelle_id, version_id)
            doc = doc_ref.get()
            if not doc.exists:
                return None
            data = doc.to_dict() or {}
            data['id'] = doc.id
            return data
        except Exception as e:
            logger.error(f"Error fetching result refinement version {version_id}: {e}")
            return None

    async def save_result_refinement_version(
        self, user_id: str, kapitel_id: str, run_id: str, quelle_id: str, version_id: str, data: dict
    ) -> None:
        """Create/overwrite a per-result refinement version doc."""
        doc_ref = self._run_result_refinement_version_ref(user_id, kapitel_id, run_id, quelle_id, version_id)
        doc_ref.set(data)

    async def update_result_refinement_version(
        self, user_id: str, kapitel_id: str, run_id: str, quelle_id: str, version_id: str, data: dict
    ) -> None:
        """Update a per-result refinement version doc."""
        doc_ref = self._run_result_refinement_version_ref(user_id, kapitel_id, run_id, quelle_id, version_id)
        doc_ref.update(data)

    async def ensure_result_refinement_root_version(
        self, user_id: str, kapitel_id: str, run_id: str, quelle_id: str, max_depth: int
    ) -> dict:
        """
        Ensure the refinement root version exists under results/{quelleId}/versions/root.

        Also ensures results/{quelleId} has refinement metadata fields initialized.
        """
        result = await self.get_run_result(user_id, kapitel_id, run_id, quelle_id)
        if not result:
            raise ValueError("Result not found for this Quelle in this run.")

        root_id = 'root'
        root_doc = await self.get_result_refinement_version(user_id, kapitel_id, run_id, quelle_id, root_id)
        if not root_doc:
            created_at = result.get("createdAt") or SERVER_TIMESTAMP
            usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
            root_data = {
                "parentVersionId": None,
                "depth": 0,
                "userMessage": None,
                "assistantText": result.get("content") or "",
                "hasContent": bool(result.get("hasContent", True)),
                "status": "success",
                "model": result.get("model") or "",
                "usage": {
                    "inputTokens": int(usage.get("inputTokens", 0)),
                    "cachedInputTokens": int(usage.get("cachedInputTokens", 0)),
                    "outputTokens": int(usage.get("outputTokens", 0)),
                    "reasoningTokens": int(usage.get("reasoningTokens", 0)),
                    "totalTokens": int(usage.get("totalTokens", 0)),
                },
                "costUsd": 0.0,
                "keySource": result.get("keySource"),
                "createdAt": created_at,
            }
            await self.save_result_refinement_version(user_id, kapitel_id, run_id, quelle_id, root_id, root_data)

        # Initialize refinement metadata on result doc (merge, idempotent)
        result_ref = self._run_result_ref(user_id, kapitel_id, run_id, quelle_id)
        existing_refinement = result.get("refinement") if isinstance(result.get("refinement"), dict) else {}
        active_id = existing_refinement.get("activeVersionId") or "root"
        refinement_doc = {
            "rootVersionId": "root",
            "activeVersionId": active_id,
            "maxDepth": int(max_depth),
            "costTotalUsd": float(existing_refinement.get("costTotalUsd") or 0.0),
            "initializedAt": existing_refinement.get("initializedAt") or SERVER_TIMESTAMP,
        }
        if "selectedAt" in existing_refinement:
            refinement_doc["selectedAt"] = existing_refinement.get("selectedAt")
        result_ref.set({"refinement": refinement_doc, "updatedAt": SERVER_TIMESTAMP}, merge=True)

        return {
            'root_version_id': 'root',
            'active_version_id': active_id,
            'max_depth': max_depth,
        }

    async def increment_result_refinement_cost_total(
        self, user_id: str, kapitel_id: str, run_id: str, quelle_id: str, cost_usd: float
    ) -> None:
        """Increment results/{quelleId}.refinement.costTotalUsd atomically (USD)."""
        result_ref = self._run_result_ref(user_id, kapitel_id, run_id, quelle_id)
        result_ref.update(
            {
                "refinement.costTotalUsd": Increment(float(cost_usd)),
                "updatedAt": SERVER_TIMESTAMP,
            }
        )

    async def get_run(self, user_id: str, kapitel_id: str, run_id: str) -> Optional[dict]:
        """Fetch a run document for a given Kapitel."""
        try:
            run_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
            )
            doc = run_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error fetching run {run_id}: {str(e)}")
            raise

    async def get_run_results(self, user_id: str, kapitel_id: str, run_id: str) -> list:
        """Fetch all results for a run."""
        try:
            results_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('results')
            )
            snapshot = results_ref.get()
            return [
                {'id': doc.id, **doc.to_dict()}
                for doc in snapshot
            ]
        except Exception as e:
            logger.error(f"Error fetching results for run {run_id}: {str(e)}")
            raise

    async def get_combined_result(self, user_id: str, kapitel_id: str, run_id: str) -> Optional[dict]:
        """Fetch combined artifact (`artifacts/combined`) if it exists."""
        try:
            combined_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('artifacts')
                .document('combined')
            )
            doc = combined_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error fetching combined result for run {run_id}: {str(e)}")
            raise

    async def set_run_artifact_status(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        artifact_id: str,
        status: str,
    ) -> None:
        """Update runs/{runId}.artifactsStatus.{artifactId} (used to drive UI states)."""
        try:
            run_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("kapitels")
                .document(kapitel_id)
                .collection("runs")
                .document(run_id)
            )
            run_ref.set(
                {
                    f"artifactsStatus.{artifact_id}": status,
                    "lastActivityAt": SERVER_TIMESTAMP,
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
        except Exception as e:
            logger.error(f"Error setting run artifact status ({artifact_id}={status}): {e}")

    async def mark_artifact_running(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        artifact_id: str,
        *,
        model: Optional[str] = None,
        key_source: Optional[str] = None,
        used_kapitel_ids: Optional[list] = None,
        aufgabenstellung: Optional[str] = None,
    ) -> None:
        """
        Create/merge a placeholder artifact doc (status=running) so the UI can show progress and avoid infinite spinners.
        Also updates runs/{runId}.artifactsStatus.{artifactId} = "running".
        """
        try:
            doc_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('artifacts')
                .document(artifact_id)
            )

            existing = doc_ref.get()
            existing_data = existing.to_dict() if existing.exists else {}

            created_at_value = existing_data.get("createdAt") if existing.exists else SERVER_TIMESTAMP
            started_at_value = (
                existing_data.get("startedAt")
                if existing.exists and existing_data.get("startedAt") is not None
                else SERVER_TIMESTAMP
            )

            existing_refinement = existing_data.get("refinement") if isinstance(existing_data, dict) else None
            refinement_value = (
                existing_refinement
                if isinstance(existing_refinement, dict) and existing_refinement.get("rootVersionId") == "root"
                else {
                    "rootVersionId": "root",
                    "activeVersionId": "root",
                    "maxDepth": int(config.TEXT_REFINEMENT_MAX_DEPTH),
                    "costTotalUsd": 0.0,
                    "initializedAt": SERVER_TIMESTAMP,
                }
            )

            model_value = (model or "").strip() or (existing_data.get("model") or "")

            placeholder: dict = {
                "artifactId": artifact_id,
                "status": "running",
                "errorMessage": None,
                "errorAt": None,
                "model": model_value,
                "usage": {
                    "inputTokens": 0,
                    "cachedInputTokens": 0,
                    "outputTokens": 0,
                    "reasoningTokens": 0,
                    "totalTokens": 0,
                },
                "costUsd": 0.0,
                "keySource": key_source,
                "createdAt": created_at_value,
                "startedAt": started_at_value,
                "updatedAt": SERVER_TIMESTAMP,
                "finishedAt": None,
                "refinement": refinement_value,
            }

            if artifact_id == "combined":
                placeholder.update(
                    {
                        "content": "",
                        "heading": existing_data.get("heading") or "",
                        "topic": existing_data.get("topic") or "",
                        "sourceQuelleIds": [],
                    }
                )
            elif artifact_id == "shortened":
                placeholder.update(
                    {
                        "content": "",
                        "originalLength": 0,
                        "shortenedLength": 0,
                        "compressionRatio": 0.0,
                        "usedKapitelIds": used_kapitel_ids or [],
                    }
                )
            elif artifact_id == "lesefluss":
                placeholder.update(
                    {
                        "content": "",
                        "aufgabenstellung": aufgabenstellung or (existing_data.get("aufgabenstellung") or ""),
                        "originalLength": 0,
                        "leseflussLength": 0,
                        "usedKapitelIds": used_kapitel_ids or [],
                    }
                )

            batch = self.db.batch()
            batch.set(doc_ref, placeholder, merge=True)

            run_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("kapitels")
                .document(kapitel_id)
                .collection("runs")
                .document(run_id)
            )
            batch.set(
                run_ref,
                {
                    f"artifactsStatus.{artifact_id}": "running",
                    "lastActivityAt": SERVER_TIMESTAMP,
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
            batch.commit()
        except Exception as e:
            logger.error(f"Error marking artifact running ({artifact_id}): {e}")

    async def mark_artifact_error(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        artifact_id: str,
        *,
        key_source: Optional[str] = None,
    ) -> None:
        """Mark an artifact doc as errored (status=error) with a generic message."""
        try:
            doc_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('artifacts')
                .document(artifact_id)
            )

            existing = doc_ref.get()
            existing_data = existing.to_dict() if existing.exists else {}

            created_at_value = existing_data.get("createdAt") if existing.exists else SERVER_TIMESTAMP
            started_at_value = (
                existing_data.get("startedAt")
                if existing.exists and existing_data.get("startedAt") is not None
                else SERVER_TIMESTAMP
            )

            update = {
                "artifactId": artifact_id,
                "status": "error",
                "errorMessage": AI_GENERIC_ERROR_MESSAGE,
                "errorAt": SERVER_TIMESTAMP,
                "keySource": key_source,
                "createdAt": created_at_value,
                "startedAt": started_at_value,
                "updatedAt": SERVER_TIMESTAMP,
                "finishedAt": SERVER_TIMESTAMP,
            }

            batch = self.db.batch()
            batch.set(doc_ref, update, merge=True)

            run_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("kapitels")
                .document(kapitel_id)
                .collection("runs")
                .document(run_id)
            )
            batch.set(
                run_ref,
                {
                    f"artifactsStatus.{artifact_id}": "error",
                    "lastActivityAt": SERVER_TIMESTAMP,
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
            batch.commit()
        except Exception as e:
            logger.error(f"Error marking artifact error ({artifact_id}): {e}")

    def _combined_root_ref(self, user_id: str, kapitel_id: str, run_id: str):
        return (
            self.db.collection('users')
            .document(user_id)
            .collection('kapitels')
            .document(kapitel_id)
            .collection('runs')
            .document(run_id)
            .collection('artifacts')
            .document('combined')
        )

    def _combined_refinement_version_ref(
        self, user_id: str, kapitel_id: str, run_id: str, version_id: str
    ):
        return self._combined_root_ref(user_id, kapitel_id, run_id).collection('versions').document(version_id)

    async def get_combined_refinement_version(
        self, user_id: str, kapitel_id: str, run_id: str, version_id: str
    ) -> Optional[dict]:
        """Fetch a combined text refinement version (if it exists)."""
        try:
            doc_ref = self._combined_refinement_version_ref(user_id, kapitel_id, run_id, version_id)
            doc = doc_ref.get()
            if not doc.exists:
                return None
            data = doc.to_dict() or {}
            data['id'] = doc.id
            return data
        except Exception as e:
            logger.error(f"Error fetching combined refinement version {version_id}: {e}")
            return None

    async def save_combined_refinement_version(
        self, user_id: str, kapitel_id: str, run_id: str, version_id: str, data: dict
    ) -> None:
        """Create/overwrite a combined refinement version doc."""
        doc_ref = self._combined_refinement_version_ref(user_id, kapitel_id, run_id, version_id)
        doc_ref.set(data)

    async def update_combined_refinement_version(
        self, user_id: str, kapitel_id: str, run_id: str, version_id: str, data: dict
    ) -> None:
        """Update a combined refinement version doc."""
        doc_ref = self._combined_refinement_version_ref(user_id, kapitel_id, run_id, version_id)
        doc_ref.update(data)

    async def ensure_combined_refinement_root_version(
        self, user_id: str, kapitel_id: str, run_id: str, max_depth: int
    ) -> dict:
        """
        Ensure the refinement root version exists under artifacts/combined/versions/root.

        Also ensures artifacts/combined has refinement metadata initialized.
        """
        combined = await self.get_combined_result(user_id, kapitel_id, run_id)
        if not combined:
            raise ValueError("No combined result found for this run.")

        combined_content = combined.get("content") or ""
        if not combined_content:
            raise ValueError("Combined content is empty.")

        root_id = 'root'
        root_doc = await self.get_combined_refinement_version(user_id, kapitel_id, run_id, root_id)
        if not root_doc:
            created_at = combined.get("createdAt") or SERVER_TIMESTAMP
            usage = combined.get("usage") if isinstance(combined.get("usage"), dict) else {}
            root_data = {
                "parentVersionId": None,
                "depth": 0,
                "userMessage": None,
                "assistantText": combined_content,
                "hasContent": True,
                "status": "success",
                "model": combined.get("model") or "",
                "usage": {
                    "inputTokens": int(usage.get("inputTokens", 0)),
                    "cachedInputTokens": int(usage.get("cachedInputTokens", 0)),
                    "outputTokens": int(usage.get("outputTokens", 0)),
                    "reasoningTokens": int(usage.get("reasoningTokens", 0)),
                    "totalTokens": int(usage.get("totalTokens", 0)),
                },
                "costUsd": 0.0,
                "keySource": combined.get("keySource"),
                "createdAt": created_at,
            }
            await self.save_combined_refinement_version(user_id, kapitel_id, run_id, root_id, root_data)

        # Initialize refinement metadata on combined doc (merge, idempotent).
        combined_ref = self._combined_root_ref(user_id, kapitel_id, run_id)
        existing_refinement = combined.get("refinement") if isinstance(combined.get("refinement"), dict) else {}
        active_id = existing_refinement.get("activeVersionId") or "root"
        refinement_doc = {
            "rootVersionId": "root",
            "activeVersionId": active_id,
            "maxDepth": int(max_depth),
            "costTotalUsd": float(existing_refinement.get("costTotalUsd") or 0.0),
            "initializedAt": existing_refinement.get("initializedAt") or SERVER_TIMESTAMP,
        }
        if "selectedAt" in existing_refinement:
            refinement_doc["selectedAt"] = existing_refinement.get("selectedAt")
        combined_ref.set({"refinement": refinement_doc, "updatedAt": SERVER_TIMESTAMP}, merge=True)

        return {
            'root_version_id': 'root',
            'active_version_id': active_id,
            'max_depth': max_depth,
        }

    async def increment_combined_refinement_cost_total(
        self, user_id: str, kapitel_id: str, run_id: str, cost_usd: float
    ) -> None:
        """Increment artifacts/combined.refinement.costTotalUsd atomically (USD)."""
        combined_ref = self._combined_root_ref(user_id, kapitel_id, run_id)
        combined_ref.update(
            {
                "refinement.costTotalUsd": Increment(float(cost_usd)),
                "updatedAt": SERVER_TIMESTAMP,
            }
        )

    def _shortened_root_ref(self, user_id: str, kapitel_id: str, run_id: str):
        return (
            self.db.collection('users')
            .document(user_id)
            .collection('kapitels')
            .document(kapitel_id)
            .collection('runs')
            .document(run_id)
            .collection('artifacts')
            .document('shortened')
        )

    def _shortened_refinement_version_ref(
        self, user_id: str, kapitel_id: str, run_id: str, version_id: str
    ):
        return self._shortened_root_ref(user_id, kapitel_id, run_id).collection('versions').document(version_id)

    async def get_shortened_refinement_version(
        self, user_id: str, kapitel_id: str, run_id: str, version_id: str
    ) -> Optional[dict]:
        """Fetch a shortened text refinement version (if it exists)."""
        try:
            doc_ref = self._shortened_refinement_version_ref(user_id, kapitel_id, run_id, version_id)
            doc = doc_ref.get()
            if not doc.exists:
                return None
            data = doc.to_dict() or {}
            data['id'] = doc.id
            return data
        except Exception as e:
            logger.error(f"Error fetching shortened refinement version {version_id}: {e}")
            return None

    async def save_shortened_refinement_version(
        self, user_id: str, kapitel_id: str, run_id: str, version_id: str, data: dict
    ) -> None:
        """Create/overwrite a shortened refinement version doc."""
        doc_ref = self._shortened_refinement_version_ref(user_id, kapitel_id, run_id, version_id)
        doc_ref.set(data)

    async def update_shortened_refinement_version(
        self, user_id: str, kapitel_id: str, run_id: str, version_id: str, data: dict
    ) -> None:
        """Update a shortened refinement version doc."""
        doc_ref = self._shortened_refinement_version_ref(user_id, kapitel_id, run_id, version_id)
        doc_ref.update(data)

    async def ensure_shortened_refinement_root_version(
        self, user_id: str, kapitel_id: str, run_id: str, max_depth: int
    ) -> dict:
        """
        Ensure the refinement root version exists under artifacts/shortened/versions/root.

        Also ensures artifacts/shortened has refinement metadata initialized.
        """
        shortened = await self.get_shortened_result(user_id, kapitel_id, run_id)
        if not shortened:
            raise ValueError("No shortened result found for this run.")

        shortened_content = shortened.get("content") or ""
        if not shortened_content:
            raise ValueError("Shortened content is empty.")

        root_id = 'root'
        root_doc = await self.get_shortened_refinement_version(user_id, kapitel_id, run_id, root_id)
        if not root_doc:
            created_at = shortened.get("createdAt") or SERVER_TIMESTAMP
            usage = shortened.get("usage") if isinstance(shortened.get("usage"), dict) else {}

            root_data = {
                "parentVersionId": None,
                "depth": 0,
                "userMessage": None,
                "assistantText": shortened_content,
                "hasContent": True,
                "status": "success",
                "model": shortened.get("model") or "",
                "usage": {
                    "inputTokens": int(usage.get("inputTokens", 0)),
                    "cachedInputTokens": int(usage.get("cachedInputTokens", 0)),
                    "outputTokens": int(usage.get("outputTokens", 0)),
                    "reasoningTokens": int(usage.get("reasoningTokens", 0)),
                    "totalTokens": int(usage.get("totalTokens", 0)),
                },
                "costUsd": 0.0,
                "keySource": shortened.get("keySource"),
                "createdAt": created_at,
            }
            await self.save_shortened_refinement_version(user_id, kapitel_id, run_id, root_id, root_data)

        # Initialize refinement metadata on shortened doc (merge, idempotent)
        shortened_ref = self._shortened_root_ref(user_id, kapitel_id, run_id)
        existing_refinement = shortened.get("refinement") if isinstance(shortened.get("refinement"), dict) else {}
        active_id = existing_refinement.get("activeVersionId") or "root"
        refinement_doc = {
            "rootVersionId": "root",
            "activeVersionId": active_id,
            "maxDepth": int(max_depth),
            "costTotalUsd": float(existing_refinement.get("costTotalUsd") or 0.0),
            "initializedAt": existing_refinement.get("initializedAt") or SERVER_TIMESTAMP,
        }
        if "selectedAt" in existing_refinement:
            refinement_doc["selectedAt"] = existing_refinement.get("selectedAt")
        shortened_ref.set({"refinement": refinement_doc, "updatedAt": SERVER_TIMESTAMP}, merge=True)

        return {
            'root_version_id': 'root',
            'active_version_id': active_id,
            'max_depth': max_depth,
        }

    async def increment_shortened_refinement_cost_total(
        self, user_id: str, kapitel_id: str, run_id: str, cost_usd: float
    ) -> None:
        """Increment artifacts/shortened.refinement.costTotalUsd atomically (USD)."""
        shortened_ref = self._shortened_root_ref(user_id, kapitel_id, run_id)
        shortened_ref.update(
            {
                "refinement.costTotalUsd": Increment(float(cost_usd)),
                "updatedAt": SERVER_TIMESTAMP,
            }
        )

    def _lesefluss_root_ref(self, user_id: str, kapitel_id: str, run_id: str):
        return (
            self.db.collection('users')
            .document(user_id)
            .collection('kapitels')
            .document(kapitel_id)
            .collection('runs')
            .document(run_id)
            .collection('artifacts')
            .document('lesefluss')
        )

    def _lesefluss_refinement_version_ref(
        self, user_id: str, kapitel_id: str, run_id: str, version_id: str
    ):
        return self._lesefluss_root_ref(user_id, kapitel_id, run_id).collection('versions').document(version_id)

    async def get_lesefluss_refinement_version(
        self, user_id: str, kapitel_id: str, run_id: str, version_id: str
    ) -> Optional[dict]:
        """Fetch a lesefluss text refinement version (if it exists)."""
        try:
            doc_ref = self._lesefluss_refinement_version_ref(user_id, kapitel_id, run_id, version_id)
            doc = doc_ref.get()
            if not doc.exists:
                return None
            data = doc.to_dict() or {}
            data['id'] = doc.id
            return data
        except Exception as e:
            logger.error(f"Error fetching lesefluss refinement version {version_id}: {e}")
            return None

    async def save_lesefluss_refinement_version(
        self, user_id: str, kapitel_id: str, run_id: str, version_id: str, data: dict
    ) -> None:
        """Create/overwrite a lesefluss refinement version doc."""
        doc_ref = self._lesefluss_refinement_version_ref(user_id, kapitel_id, run_id, version_id)
        doc_ref.set(data)

    async def update_lesefluss_refinement_version(
        self, user_id: str, kapitel_id: str, run_id: str, version_id: str, data: dict
    ) -> None:
        """Update a lesefluss refinement version doc."""
        doc_ref = self._lesefluss_refinement_version_ref(user_id, kapitel_id, run_id, version_id)
        doc_ref.update(data)

    async def ensure_lesefluss_refinement_root_version(
        self, user_id: str, kapitel_id: str, run_id: str, max_depth: int
    ) -> dict:
        """
        Ensure the refinement root version exists under artifacts/lesefluss/versions/root.

        Also ensures artifacts/lesefluss has refinement metadata initialized.
        """
        lesefluss = await self.get_lesefluss_result(user_id, kapitel_id, run_id)
        if not lesefluss:
            raise ValueError("No lesefluss result found for this run.")

        lesefluss_content = lesefluss.get("content") or ""
        if not lesefluss_content:
            raise ValueError("Lesefluss content is empty.")

        root_id = 'root'
        root_doc = await self.get_lesefluss_refinement_version(user_id, kapitel_id, run_id, root_id)
        if not root_doc:
            created_at = lesefluss.get("createdAt") or SERVER_TIMESTAMP
            usage = lesefluss.get("usage") if isinstance(lesefluss.get("usage"), dict) else {}

            root_data = {
                "parentVersionId": None,
                "depth": 0,
                "userMessage": None,
                "assistantText": lesefluss_content,
                "hasContent": True,
                "status": "success",
                "model": lesefluss.get("model") or "",
                "usage": {
                    "inputTokens": int(usage.get("inputTokens", 0)),
                    "cachedInputTokens": int(usage.get("cachedInputTokens", 0)),
                    "outputTokens": int(usage.get("outputTokens", 0)),
                    "reasoningTokens": int(usage.get("reasoningTokens", 0)),
                    "totalTokens": int(usage.get("totalTokens", 0)),
                },
                "costUsd": 0.0,
                "keySource": lesefluss.get("keySource"),
                "createdAt": created_at,
            }
            await self.save_lesefluss_refinement_version(user_id, kapitel_id, run_id, root_id, root_data)

        # Initialize refinement metadata on lesefluss doc (merge, idempotent)
        lesefluss_ref = self._lesefluss_root_ref(user_id, kapitel_id, run_id)
        existing_refinement = lesefluss.get("refinement") if isinstance(lesefluss.get("refinement"), dict) else {}
        active_id = existing_refinement.get("activeVersionId") or "root"
        refinement_doc = {
            "rootVersionId": "root",
            "activeVersionId": active_id,
            "maxDepth": int(max_depth),
            "costTotalUsd": float(existing_refinement.get("costTotalUsd") or 0.0),
            "initializedAt": existing_refinement.get("initializedAt") or SERVER_TIMESTAMP,
        }
        if "selectedAt" in existing_refinement:
            refinement_doc["selectedAt"] = existing_refinement.get("selectedAt")
        lesefluss_ref.set({"refinement": refinement_doc, "updatedAt": SERVER_TIMESTAMP}, merge=True)

        return {
            'root_version_id': 'root',
            'active_version_id': active_id,
            'max_depth': max_depth,
        }

    async def increment_lesefluss_refinement_cost_total(
        self, user_id: str, kapitel_id: str, run_id: str, cost_usd: float
    ) -> None:
        """Increment artifacts/lesefluss.refinement.costTotalUsd atomically (USD)."""
        lesefluss_ref = self._lesefluss_root_ref(user_id, kapitel_id, run_id)
        lesefluss_ref.update(
            {
                "refinement.costTotalUsd": Increment(float(cost_usd)),
                "updatedAt": SERVER_TIMESTAMP,
            }
        )

    async def save_combined_result(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        combined_content: str,
        source_quelle_ids: list,
        heading: str,
        topic: str,
        model_used: str,
        tokens_used: int,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int,
        cost: float,
        key_source: Optional[str] = None,
    ) -> str:
        """
        Save combined artifact under a run (`artifacts/combined`).
        """
        try:
            combined_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('artifacts')
                .document('combined')
            )

            existing = combined_ref.get()
            existing_data = existing.to_dict() if existing.exists else {}

            created_at_value = existing_data.get("createdAt") if existing.exists else SERVER_TIMESTAMP
            started_at_value = (
                existing_data.get("startedAt")
                if existing.exists and existing_data.get("startedAt") is not None
                else created_at_value
            )
            existing_refinement = existing_data.get("refinement") if isinstance(existing_data, dict) else None
            refinement_value = (
                existing_refinement
                if isinstance(existing_refinement, dict) and existing_refinement.get("rootVersionId") == "root"
                else {
                    "rootVersionId": "root",
                    "activeVersionId": "root",
                    "maxDepth": int(config.TEXT_REFINEMENT_MAX_DEPTH),
                    "costTotalUsd": 0.0,
                    "initializedAt": SERVER_TIMESTAMP,
                }
            )

            combined_data = {
                "artifactId": "combined",
                "status": "success",
                "errorMessage": None,
                "errorAt": None,
                "content": combined_content,
                "heading": heading,
                "topic": topic,
                "sourceQuelleIds": source_quelle_ids,
                "model": model_used,
                "usage": {
                    "inputTokens": int(input_tokens),
                    "cachedInputTokens": int(cached_input_tokens),
                    "outputTokens": int(output_tokens),
                    "reasoningTokens": int(reasoning_tokens),
                    "totalTokens": int(tokens_used),
                },
                "costUsd": float(cost),
                "keySource": key_source,
                "createdAt": created_at_value,
                "startedAt": started_at_value,
                "updatedAt": SERVER_TIMESTAMP,
                "finishedAt": SERVER_TIMESTAMP,
                "refinement": refinement_value,
            }

            batch = self.db.batch()
            batch.set(combined_ref, combined_data)

            run_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("kapitels")
                .document(kapitel_id)
                .collection("runs")
                .document(run_id)
            )
            batch.set(
                run_ref,
                {
                    "artifactsStatus.combined": "success",
                    "lastActivityAt": SERVER_TIMESTAMP,
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )

            # Mark Kapitel latest run as "done" once a combined artifact exists for that run.
            # This drives UI Kapitel status (denormalized via `kapitels.latestRun.status`).
            try:
                kapitel_ref = (
                    self.db.collection("users")
                    .document(user_id)
                    .collection("kapitels")
                    .document(kapitel_id)
                )
                kapitel_doc = kapitel_ref.get()
                kapitel_data = kapitel_doc.to_dict() if kapitel_doc.exists else {}
                latest_run = kapitel_data.get("latestRun") if isinstance(kapitel_data, dict) else None
                if isinstance(latest_run, dict) and latest_run.get("runId") == run_id:
                    batch.update(
                        kapitel_ref,
                        {
                            "latestRun.status": "done",
                            "latestRun.updatedAt": SERVER_TIMESTAMP,
                            "updatedAt": SERVER_TIMESTAMP,
                        },
                    )
            except Exception as e:
                # Non-fatal: combined is saved, but Kapitel status may lag until next write.
                logger.warning(
                    f"Could not update Kapitel.latestRun status for kapitel {kapitel_id} run {run_id}: {e}"
                )

            batch.commit()
            logger.info(
                f"Saved combined result for kapitel {kapitel_id} run {run_id} (cost: ${cost:.6f})"
            )
            return combined_ref.id
        except Exception as e:
            logger.error(f"Error saving combined result: {str(e)}")
            raise

    async def save_intermediate_group_result(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        group_number: int,
        combined_content: str,
        source_quelle_ids: list,
        heading: str,
        topic: str,
        model_used: str,
        tokens_used: int,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int,
        cost: float,
        key_source: Optional[str] = None,
    ) -> str:
        """
        Save intermediate group combination result.
        Document ID will be group_{group_number}.
        """
        try:
            group_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('artifacts')
                .document('combined')
                .collection('groups')
                .document(f'group_{group_number}')
            )

            group_data = {
                "status": "success",
                "errorMessage": None,
                "errorAt": None,
                "groupNumber": int(group_number),
                "content": combined_content,
                "heading": heading,
                "topic": topic,
                "sourceQuelleIds": source_quelle_ids,
                "model": model_used,
                "usage": {
                    "inputTokens": int(input_tokens),
                    "cachedInputTokens": int(cached_input_tokens),
                    "outputTokens": int(output_tokens),
                    "reasoningTokens": int(reasoning_tokens),
                    "totalTokens": int(tokens_used),
                },
                "costUsd": float(cost),
                "keySource": key_source,
                "createdAt": SERVER_TIMESTAMP,
                "updatedAt": SERVER_TIMESTAMP,
                "finishedAt": SERVER_TIMESTAMP,
            }

            batch = self.db.batch()
            batch.set(group_ref, group_data)

            run_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("kapitels")
                .document(kapitel_id)
                .collection("runs")
                .document(run_id)
            )
            batch.set(
                run_ref,
                {
                    "lastActivityAt": SERVER_TIMESTAMP,
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
            batch.commit()
            logger.info(
                f"Saved intermediate group {group_number} for kapitel {kapitel_id} run {run_id} "
                f"(sources: {len(source_quelle_ids)}, cost: ${cost:.6f})"
            )
            return group_ref.id
        except Exception as e:
            logger.error(f"Error saving intermediate group result: {str(e)}")
            raise

    async def get_intermediate_groups(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str
    ) -> list:
        """
        Fetch all combined intermediate groups for a run, ordered by groupNumber.
        Returns list of dicts with group data.
        """
        try:
            groups_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('artifacts')
                .document('combined')
                .collection('groups')
            )

            docs = groups_ref.stream()
            groups = []
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                groups.append(data)

            groups.sort(key=lambda x: x.get('groupNumber', 0))
            return groups
        except Exception as e:
            logger.error(f"Error fetching intermediate groups: {str(e)}")
            raise

    async def get_kapitel(self, user_id: str, kapitel_id: str) -> Optional[dict]:
        """Fetch a Kapitel document."""
        try:
            kapitel_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
            )
            doc = kapitel_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error fetching kapitel {kapitel_id}: {str(e)}")
            raise

    async def get_project(self, user_id: str, project_id: str) -> Optional[dict]:
        """Fetch a Project document (`users/{uid}/projects/{projectId}`)."""
        try:
            project_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("projects")
                .document(project_id)
            )
            doc = project_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error fetching project {project_id}: {str(e)}")
            raise

    async def check_all_quellen_processed(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str
    ) -> Tuple[bool, int]:
        """
        Check if all Quellen in a Kapitel have been processed for a specific run.

        Returns:
            tuple: (all_processed: bool, content_count: int)
                - all_processed: True if all Quellen have results
                - content_count: Number of results with usable content
        """
        try:
            # Get the Kapitel to know which Quellen should be processed
            kapitel = await self.get_kapitel(user_id, kapitel_id)
            if not kapitel:
                logger.warning(f"Kapitel {kapitel_id} not found")
                return False, 0

            quelle_ids = kapitel.get('quelleIds', [])
            if not quelle_ids:
                logger.warning(f"No Quellen assigned to Kapitel {kapitel_id}")
                return False, 0

            # Get all results for this run
            results = await self.get_run_results(user_id, kapitel_id, run_id)
            results_by_id = {r["id"]: r for r in results}
            result_ids = set(results_by_id.keys())

            # Check if all Quellen have results
            all_present = all(quelle_id in result_ids for quelle_id in quelle_ids)
            all_finished = False
            if all_present:
                all_finished = all(
                    (str(results_by_id[quelle_id].get("status") or "").strip() != "running")
                    for quelle_id in quelle_ids
                )
            all_processed = all_present and all_finished

            # Count results with usable content
            content_count = sum(
                1
                for r in results
                if bool(r.get("hasContent", True)) and (r.get("content") or "").strip()
            )

            logger.info(
                f"Kapitel {kapitel_id} run {run_id}: "
                f"{len(result_ids)}/{len(quelle_ids)} result docs, "
                f"all_present={all_present}, all_finished={all_finished}, "
                f"{content_count} with content"
            )

            return all_processed, content_count

        except Exception as e:
            logger.error(f"Error checking if all Quellen processed: {str(e)}")
            raise

    async def get_shortened_result(self, user_id: str, kapitel_id: str, run_id: str) -> Optional[dict]:
        """Fetch shortened artifact (`artifacts/shortened`) if it exists."""
        try:
            shortened_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('artifacts')
                .document('shortened')
            )
            doc = shortened_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error fetching shortened result for run {run_id}: {str(e)}")
            raise

    async def save_shortened_result(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        shortened_data: dict
    ) -> str:
        """
        Save shortened artifact under a run (`artifacts/shortened`).
        """
        try:
            shortened_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('artifacts')
                .document('shortened')
            )

            existing = shortened_ref.get()
            existing_data = existing.to_dict() if existing.exists else {}

            created_at_value = existing_data.get("createdAt") if existing.exists else SERVER_TIMESTAMP
            started_at_value = (
                existing_data.get("startedAt")
                if existing.exists and existing_data.get("startedAt") is not None
                else created_at_value
            )
            existing_refinement = existing_data.get("refinement") if isinstance(existing_data, dict) else None
            refinement_value = (
                existing_refinement
                if isinstance(existing_refinement, dict) and existing_refinement.get("rootVersionId") == "root"
                else {
                    "rootVersionId": "root",
                    "activeVersionId": "root",
                    "maxDepth": int(config.TEXT_REFINEMENT_MAX_DEPTH),
                    "costTotalUsd": 0.0,
                    "initializedAt": SERVER_TIMESTAMP,
                }
            )

            usage = shortened_data.get("usage") if isinstance(shortened_data.get("usage"), dict) else {}
            v2_doc = {
                "artifactId": "shortened",
                "status": "success",
                "errorMessage": None,
                "errorAt": None,
                "content": shortened_data.get("content") or "",
                "originalLength": int(shortened_data.get("originalLength") or 0),
                "shortenedLength": int(shortened_data.get("shortenedLength") or 0),
                "compressionRatio": float(shortened_data.get("compressionRatio") or 0.0),
                "usedKapitelIds": shortened_data.get("usedKapitelIds") or [],
                "model": shortened_data.get("model") or "",
                "usage": {
                    "inputTokens": int(usage.get("inputTokens", 0)),
                    "cachedInputTokens": int(usage.get("cachedInputTokens", 0)),
                    "outputTokens": int(usage.get("outputTokens", 0)),
                    "reasoningTokens": int(usage.get("reasoningTokens", 0)),
                    "totalTokens": int(usage.get("totalTokens", 0)),
                },
                "costUsd": float(shortened_data.get("costUsd") or 0.0),
                "keySource": shortened_data.get("keySource"),
                "createdAt": created_at_value,
                "startedAt": started_at_value,
                "updatedAt": SERVER_TIMESTAMP,
                "finishedAt": SERVER_TIMESTAMP,
                "refinement": refinement_value,
            }

            batch = self.db.batch()
            batch.set(shortened_ref, v2_doc)

            run_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("kapitels")
                .document(kapitel_id)
                .collection("runs")
                .document(run_id)
            )
            batch.set(
                run_ref,
                {
                    "artifactsStatus.shortened": "success",
                    "lastActivityAt": SERVER_TIMESTAMP,
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
            batch.commit()
            logger.info(
                f"Saved shortened result for kapitel {kapitel_id} run {run_id} "
                f"(cost: ${float(shortened_data.get('costUsd') or 0.0):.4f})"
            )
            return shortened_ref.id
        except Exception as e:
            logger.error(f"Error saving shortened result: {str(e)}")
            raise

    async def get_lesefluss_result(
        self, user_id: str, kapitel_id: str, run_id: str
    ) -> Optional[dict]:
        """Get lesefluss result for a specific run."""
        try:
            doc_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('artifacts')
                .document('lesefluss')
            )

            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                data['id'] = doc.id
                return data
            return None
        except Exception as e:
            logger.error(f"Error getting lesefluss result: {e}")
            return None

    async def save_lesefluss_result(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        lesefluss_data: dict
    ) -> None:
        """Save lesefluss artifact to Firestore (`artifacts/lesefluss`)."""
        try:
            doc_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('artifacts')
                .document('lesefluss')
            )

            existing = doc_ref.get()
            existing_data = existing.to_dict() if existing.exists else {}

            created_at_value = existing_data.get("createdAt") if existing.exists else SERVER_TIMESTAMP
            started_at_value = (
                existing_data.get("startedAt")
                if existing.exists and existing_data.get("startedAt") is not None
                else created_at_value
            )
            existing_refinement = existing_data.get("refinement") if isinstance(existing_data, dict) else None
            refinement_value = (
                existing_refinement
                if isinstance(existing_refinement, dict) and existing_refinement.get("rootVersionId") == "root"
                else {
                    "rootVersionId": "root",
                    "activeVersionId": "root",
                    "maxDepth": int(config.TEXT_REFINEMENT_MAX_DEPTH),
                    "costTotalUsd": 0.0,
                    "initializedAt": SERVER_TIMESTAMP,
                }
            )

            usage = lesefluss_data.get("usage") if isinstance(lesefluss_data.get("usage"), dict) else {}
            v2_doc = {
                "artifactId": "lesefluss",
                "status": "success",
                "errorMessage": None,
                "errorAt": None,
                "content": lesefluss_data.get("content") or "",
                "aufgabenstellung": lesefluss_data.get("aufgabenstellung") or "",
                "originalLength": int(lesefluss_data.get("originalLength") or 0),
                "leseflussLength": int(lesefluss_data.get("leseflussLength") or 0),
                "usedKapitelIds": lesefluss_data.get("usedKapitelIds") or [],
                "model": lesefluss_data.get("model") or "",
                "usage": {
                    "inputTokens": int(usage.get("inputTokens", 0)),
                    "cachedInputTokens": int(usage.get("cachedInputTokens", 0)),
                    "outputTokens": int(usage.get("outputTokens", 0)),
                    "reasoningTokens": int(usage.get("reasoningTokens", 0)),
                    "totalTokens": int(usage.get("totalTokens", 0)),
                },
                "costUsd": float(lesefluss_data.get("costUsd") or 0.0),
                "keySource": lesefluss_data.get("keySource"),
                "createdAt": created_at_value,
                "startedAt": started_at_value,
                "updatedAt": SERVER_TIMESTAMP,
                "finishedAt": SERVER_TIMESTAMP,
                "refinement": refinement_value,
            }

            batch = self.db.batch()
            batch.set(doc_ref, v2_doc)

            run_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("kapitels")
                .document(kapitel_id)
                .collection("runs")
                .document(run_id)
            )
            batch.set(
                run_ref,
                {
                    "artifactsStatus.lesefluss": "success",
                    "lastActivityAt": SERVER_TIMESTAMP,
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
            batch.commit()
            logger.info(
                f"Saved lesefluss result for kapitel {kapitel_id}, run {run_id}"
            )
        except Exception as e:
            logger.error(f"Error saving lesefluss result: {e}")
            raise

    async def get_summary_result(
        self,
        user_id: str,
        target_kapitel_id: str,
        target_run_id: str,
        source_kapitel_id: str
    ) -> Optional[dict]:
        """Fetch a summary result for a specific source Kapitel."""
        try:
            summary_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(target_kapitel_id)
                .collection('runs')
                .document(target_run_id)
                .collection('summaries')
                .document(source_kapitel_id)
            )
            doc = summary_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(
                f"Error fetching summary for source Kapitel {source_kapitel_id}: {str(e)}"
            )
            raise

    async def mark_summary_running(
        self,
        user_id: str,
        target_kapitel_id: str,
        target_run_id: str,
        source_kapitel_id: str,
        *,
        source_run_id: str,
        source_type: str,
        model: str,
        key_source: Optional[str] = None,
    ) -> None:
        """Create/merge a placeholder summary doc (status=running)."""
        try:
            summary_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(target_kapitel_id)
                .collection('runs')
                .document(target_run_id)
                .collection('summaries')
                .document(source_kapitel_id)
            )

            existing = summary_ref.get()
            existing_data = existing.to_dict() if existing.exists else {}
            created_at_value = existing_data.get("createdAt") if existing.exists else SERVER_TIMESTAMP
            started_at_value = (
                existing_data.get("startedAt")
                if existing.exists and existing_data.get("startedAt") is not None
                else created_at_value
            )
            started_at_value = (
                existing_data.get("startedAt")
                if existing.exists and existing_data.get("startedAt") is not None
                else created_at_value
            )
            started_at_value = (
                existing_data.get("startedAt")
                if existing.exists and existing_data.get("startedAt") is not None
                else SERVER_TIMESTAMP
            )

            placeholder = {
                "status": "running",
                "errorMessage": None,
                "errorAt": None,
                "sourceKapitelId": source_kapitel_id,
                "sourceRunId": source_run_id,
                "sourceType": source_type,
                "content": "",
                "originalLength": 0,
                "summaryLength": 0,
                "model": model or "",
                "usage": {
                    "inputTokens": 0,
                    "cachedInputTokens": 0,
                    "outputTokens": 0,
                    "reasoningTokens": 0,
                    "totalTokens": 0,
                },
                "costUsd": 0.0,
                "keySource": key_source,
                "createdAt": created_at_value,
                "startedAt": started_at_value,
                "updatedAt": SERVER_TIMESTAMP,
                "finishedAt": None,
            }

            batch = self.db.batch()
            batch.set(summary_ref, placeholder, merge=True)

            run_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("kapitels")
                .document(target_kapitel_id)
                .collection("runs")
                .document(target_run_id)
            )
            batch.set(
                run_ref,
                {"lastActivityAt": SERVER_TIMESTAMP, "updatedAt": SERVER_TIMESTAMP},
                merge=True,
            )
            batch.commit()
        except Exception as e:
            logger.error(f"Error marking summary running ({source_kapitel_id}): {e}")

    async def mark_summary_error(
        self,
        user_id: str,
        target_kapitel_id: str,
        target_run_id: str,
        source_kapitel_id: str,
        *,
        key_source: Optional[str] = None,
    ) -> None:
        """Mark a summary doc as errored (status=error) with a generic message."""
        try:
            summary_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(target_kapitel_id)
                .collection('runs')
                .document(target_run_id)
                .collection('summaries')
                .document(source_kapitel_id)
            )

            existing = summary_ref.get()
            existing_data = existing.to_dict() if existing.exists else {}
            created_at_value = existing_data.get("createdAt") if existing.exists else SERVER_TIMESTAMP
            started_at_value = (
                existing_data.get("startedAt")
                if existing.exists and existing_data.get("startedAt") is not None
                else SERVER_TIMESTAMP
            )

            update = {
                "status": "error",
                "errorMessage": AI_GENERIC_ERROR_MESSAGE,
                "errorAt": SERVER_TIMESTAMP,
                "keySource": key_source,
                "createdAt": created_at_value,
                "startedAt": started_at_value,
                "updatedAt": SERVER_TIMESTAMP,
                "finishedAt": SERVER_TIMESTAMP,
            }
            summary_ref.set(update, merge=True)
        except Exception as e:
            logger.error(f"Error marking summary error ({source_kapitel_id}): {e}")

    async def save_summary_result(
        self,
        user_id: str,
        target_kapitel_id: str,
        target_run_id: str,
        source_kapitel_id: str,
        summary_data: dict
    ) -> str:
        """
        Save a summary result.
        """
        try:
            summary_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(target_kapitel_id)
                .collection('runs')
                .document(target_run_id)
                .collection('summaries')
                .document(source_kapitel_id)
            )

            existing = summary_ref.get()
            existing_data = existing.to_dict() if existing.exists else {}
            created_at_value = existing_data.get("createdAt") if existing.exists else SERVER_TIMESTAMP
            started_at_value = (
                existing_data.get("startedAt")
                if existing.exists and existing_data.get("startedAt") is not None
                else created_at_value
            )

            usage = summary_data.get("usage") if isinstance(summary_data.get("usage"), dict) else {}
            input_tokens = int(usage.get("inputTokens", 0))
            cached_input_tokens = int(usage.get("cachedInputTokens", 0))
            output_tokens = int(usage.get("outputTokens", 0))
            reasoning_tokens = int(usage.get("reasoningTokens", 0))
            total_tokens = int(usage.get("totalTokens", input_tokens + output_tokens))

            v2_doc = {
                "status": "success",
                "errorMessage": None,
                "errorAt": None,
                "sourceKapitelId": summary_data.get("sourceKapitelId") or source_kapitel_id,
                "sourceRunId": summary_data.get("sourceRunId") or "",
                "sourceType": summary_data.get("sourceType") or "",
                "content": summary_data.get("content") or "",
                "originalLength": int(summary_data.get("originalLength") or 0),
                "summaryLength": int(summary_data.get("summaryLength") or 0),
                "model": summary_data.get("model") or "",
                "usage": {
                    "inputTokens": input_tokens,
                    "cachedInputTokens": cached_input_tokens,
                    "outputTokens": output_tokens,
                    "reasoningTokens": reasoning_tokens,
                    "totalTokens": total_tokens,
                },
                "costUsd": float(summary_data.get("costUsd") or 0.0),
                "keySource": summary_data.get("keySource"),
                "createdAt": created_at_value,
                "startedAt": started_at_value,
                "updatedAt": SERVER_TIMESTAMP,
                "finishedAt": SERVER_TIMESTAMP,
            }

            batch = self.db.batch()
            batch.set(summary_ref, v2_doc)

            run_ref = (
                self.db.collection("users")
                .document(user_id)
                .collection("kapitels")
                .document(target_kapitel_id)
                .collection("runs")
                .document(target_run_id)
            )
            batch.set(
                run_ref,
                {"lastActivityAt": SERVER_TIMESTAMP, "updatedAt": SERVER_TIMESTAMP},
                merge=True,
            )
            batch.commit()
            logger.info(
                f"Saved summary for source Kapitel {source_kapitel_id} "
                f"in target Kapitel {target_kapitel_id} run {target_run_id}"
            )
            return summary_ref.id
        except Exception as e:
            logger.error(f"Error saving summary result: {str(e)}")
            raise

    async def get_kapitel_metadata(self, user_id: str, kapitel_id: str) -> Optional[dict]:
        """
        Get Kapitel metadata (id, nummer, title) for building Gliederung.

        Returns:
            dict: {'id': str, 'nummer': str, 'title': str} or None
        """
        try:
            kapitel = await self.get_kapitel(user_id, kapitel_id)
            if not kapitel:
                return None

            return {
                'id': kapitel_id,
                'nummer': kapitel.get('nummer', '?'),
                'title': kapitel.get('title', 'Untitled'),
            }
        except Exception as e:
            logger.error(f"Error fetching Kapitel metadata for {kapitel_id}: {str(e)}")
            raise

    async def list_kapitel_metadata_for_project(self, user_id: str, projekt_id: str) -> list[dict]:
        """
        List Kapitel metadata (id, nummer, title) for a given project.

        Returns:
            list[dict]: [{'id': str, 'nummer': str, 'title': str}, ...]
        """
        try:
            if not (projekt_id or "").strip():
                return []

            kapitels_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
            )
            docs = kapitels_ref.where('projektId', '==', projekt_id).stream()
            out: list[dict] = []
            for doc in docs:
                data = doc.to_dict() or {}
                out.append(
                    {
                        "id": doc.id,
                        "nummer": data.get("nummer", "?"),
                        "title": data.get("title", "Untitled"),
                    }
                )
            return out
        except Exception as e:
            logger.error(f"Error listing Kapitels for project {projekt_id}: {e}")
            return []

    async def get_kapitel_runs(self, user_id: str, kapitel_id: str) -> list:
        """
        Fetch all runs for a Kapitel.

        Returns:
            list: List of run dicts with 'id' field added
        """
        try:
            runs_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
            )
            docs = runs_ref.stream()
            runs = []
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                runs.append(data)
            return runs
        except Exception as e:
            logger.error(f"Error fetching runs for Kapitel {kapitel_id}: {str(e)}")
            raise

    async def get_kapitel_run(self, user_id: str, kapitel_id: str, run_id: str) -> Optional[dict]:
        """
        Fetch a specific run document.
        Alias for get_run() for clarity in shorten service.
        """
        return await self.get_run(user_id, kapitel_id, run_id)

    async def get_user_doc(self, user_id: str) -> Optional[dict]:
        """Fetch the user document."""
        try:
            user_ref = self.db.collection('users').document(user_id)
            doc = user_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error fetching user doc {user_id}: {str(e)}")
            raise

    async def get_allow_platform_key(self, user_id: str) -> bool:
        """Return whether the user is allowed to use the platform OpenAI key."""
        user_doc = await self.get_user_doc(user_id)
        return bool(user_doc.get('allowPlatformKey')) if user_doc else False

    async def save_user_openai_secret(self, user_id: str, data: dict) -> None:
        """
        Persist encrypted OpenAI key for the user under users/{uid}/secrets/openai.

        Expects keys: iv, ciphertext, tag, last4.
        """
        try:
            secret_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('secrets')
                .document('openai')
            )

            payload = {
                "iv": data["iv"],
                "ciphertext": data["ciphertext"],
                "tag": data["tag"],
                "last4": data.get("last4", ""),
                "updatedAt": SERVER_TIMESTAMP,
            }

            existing = secret_ref.get()
            if not existing.exists:
                payload["createdAt"] = SERVER_TIMESTAMP

            secret_ref.set(payload)
            logger.info(f"Stored encrypted OpenAI key for user {user_id}")
        except Exception as e:
            logger.error(f"Error saving OpenAI secret for user {user_id}: {str(e)}")
            raise

    async def get_user_openai_secret(self, user_id: str) -> Optional[dict]:
        """Fetch encrypted OpenAI secret for the user."""
        try:
            secret_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('secrets')
                .document('openai')
            )
            doc = secret_ref.get()
            if not doc.exists:
                return None
            data = doc.to_dict()
            return data
        except Exception as e:
            logger.error(f"Error fetching OpenAI secret for user {user_id}: {str(e)}")
            raise

    async def delete_user_openai_secret(self, user_id: str) -> None:
        """Delete the stored OpenAI secret for the user."""
        try:
            secret_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('secrets')
                .document('openai')
            )
            secret_ref.delete()
            logger.info(f"Deleted OpenAI secret for user {user_id}")
        except Exception as e:
            logger.error(f"Error deleting OpenAI secret for user {user_id}: {str(e)}")
            raise

    def _system_prompt_ref(self, stage: str, template_key: str):
        doc_id = f"{stage}__{template_key}"
        return self.db.collection("systemPromptTemplates").document(doc_id)

    async def get_system_prompt_template(self, stage: str, template_key: str) -> Optional[dict]:
        """
        Fetch a server-only system prompt template by stage and key.

        Stored at: systemPromptTemplates/{stage}__{template_key}
        """
        try:
            ref = self._system_prompt_ref(stage, template_key)
            doc = ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error fetching system prompt template {stage}/{template_key}: {e}")
            return None

    async def upsert_system_prompt_template(
        self,
        *,
        stage: str,
        template_key: str,
        name: str,
        instructions: str,
        system_prompt: Optional[str] = None,
    ) -> None:
        """
        Create or update a server-only system prompt template.
        """
        try:
            ref = self._system_prompt_ref(stage, template_key)
            existing = ref.get()
            payload = {
                "stage": stage,
                "templateKey": template_key,
                "name": name,
                "instructions": instructions,
                "updatedAt": SERVER_TIMESTAMP,
            }
            if system_prompt is not None:
                payload["systemPrompt"] = system_prompt
            if not existing.exists:
                payload["createdAt"] = SERVER_TIMESTAMP
            ref.set(payload, merge=True)
        except Exception as e:
            logger.error(f"Error upserting system prompt template {stage}/{template_key}: {e}")

    async def get_prompt_template(self, user_id: str, template_id: str) -> Optional[dict]:
        """Fetch a prompt template by id."""
        try:
            ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('promptTemplates')
                .document(template_id)
            )
            doc = ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error fetching prompt template {template_id} for user {user_id}: {e}")
            return None

    async def get_active_prompt_id(self, user_id: str, stage: str) -> Optional[str]:
        """Return active prompt id or 'default' for a stage."""
        try:
            ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('promptSettings')
                .document('active')
            )
            doc = ref.get()
            if not doc.exists:
                return None
            data = doc.to_dict() or {}
            active = data.get('activeTemplates', {})
            return active.get(stage)
        except Exception as e:
            logger.error(f"Error fetching active prompt for stage {stage}: {e}")
            return None


# Create singleton instance
firebase_service = FirebaseService()
