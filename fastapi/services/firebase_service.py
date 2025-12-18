import firebase_admin
from firebase_admin import credentials, auth, firestore
from google.cloud.firestore_v1 import SERVER_TIMESTAMP, Increment
from utils.config import config
import logging
from typing import Optional

logger = logging.getLogger(__name__)


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

    async def get_quelle(self, user_id: str, quelle_id: str) -> Optional[dict]:
        """
        Fetch a Quelle from Firestore

        Args:
            user_id: User ID (owner of the Quelle)
            quelle_id: Quelle document ID

        Returns:
            dict: Quelle data if found, None otherwise
        """
        try:
            doc_ref = self.db.collection('users').document(user_id) \
                            .collection('quellen').document(quelle_id)
            doc = doc_ref.get()

            if doc.exists:
                return doc.to_dict()
            else:
                logger.warning(f"Quelle {quelle_id} not found for user {user_id}")
                return None

        except Exception as e:
            logger.error(f"Error fetching Quelle: {str(e)}")
            raise

    async def save_result(
        self,
        user_id: str,
        quelle_id: str,
        kapitel_id: str,
        run_id: str,
        user_input: str,
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
            user_input: User's instructions
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

            result_data = {
                'quelle_id': quelle_id,
                'user_input': user_input,
                'result_content': result_content,
                'has_content': has_content,
                'model_used': model_used,
                'tokens_used': tokens_used,
                'input_tokens': input_tokens,
                'cached_input_tokens': cached_input_tokens,
                'output_tokens': output_tokens,
                'reasoning_tokens': reasoning_tokens,
                'cost': cost,
                'created_at': SERVER_TIMESTAMP
            }

            if key_source:
                result_data['key_source'] = key_source

            result_ref.set(result_data)
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
            created_at = result.get('created_at') or result.get('createdAt') or SERVER_TIMESTAMP
            root_data = {
                'parent_version_id': None,
                'depth': 0,
                'user_message': None,
                'assistant_text': result.get('result_content') or result.get('resultContent') or '',
                'has_content': result.get('has_content') if 'has_content' in result else result.get('hasContent', True),
                'status': 'success',
                'model': result.get('model_used') or result.get('modelUsed') or '',
                'usage': {
                    'input_tokens': int(result.get('input_tokens') or result.get('inputTokens') or 0),
                    'cached_input_tokens': int(result.get('cached_input_tokens') or result.get('cachedInputTokens') or 0),
                    'output_tokens': int(result.get('output_tokens') or result.get('outputTokens') or 0),
                    'reasoning_tokens': int(result.get('reasoning_tokens') or result.get('reasoningTokens') or 0),
                    'total_tokens': int(result.get('tokens_used') or result.get('tokensUsed') or 0),
                },
                'cost': 0.0,
                'created_at': created_at,
            }
            await self.save_result_refinement_version(user_id, kapitel_id, run_id, quelle_id, root_id, root_data)

        # Initialize refinement metadata on result doc (merge, idempotent)
        result_ref = self._run_result_ref(user_id, kapitel_id, run_id, quelle_id)
        active_id = (
            result.get('refinement_active_version_id')
            or result.get('refinementActiveVersionId')
            or 'root'
        )
        result_ref.set(
            {
                'refinement_root_version_id': 'root',
                'refinement_active_version_id': active_id,
                'refinement_cost_total': result.get('refinement_cost_total') or result.get('refinementCostTotal') or 0.0,
                'refinement_max_depth': max_depth,
                'refinement_initialized_at': SERVER_TIMESTAMP,
            },
            merge=True,
        )

        return {
            'root_version_id': 'root',
            'active_version_id': active_id,
            'max_depth': max_depth,
        }

    async def increment_result_refinement_cost_total(
        self, user_id: str, kapitel_id: str, run_id: str, quelle_id: str, cost_usd: float
    ) -> None:
        """Increment results/{quelleId}.refinement_cost_total atomically (USD)."""
        result_ref = self._run_result_ref(user_id, kapitel_id, run_id, quelle_id)
        result_ref.update(
            {
                'refinement_cost_total': Increment(cost_usd),
                'refinement_updated_at': SERVER_TIMESTAMP,
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
        """Fetch combined result if it exists."""
        try:
            combined_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('combined')
                .document('combined')
            )
            doc = combined_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error fetching combined result for run {run_id}: {str(e)}")
            raise

    def _combined_root_ref(self, user_id: str, kapitel_id: str, run_id: str):
        return (
            self.db.collection('users')
            .document(user_id)
            .collection('kapitels')
            .document(kapitel_id)
            .collection('runs')
            .document(run_id)
            .collection('combined')
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
        Ensure the refinement root version exists under combined/combined/versions/root.

        Also ensures combined/combined has refinement metadata fields initialized.
        """
        combined = await self.get_combined_result(user_id, kapitel_id, run_id)
        if not combined:
            raise ValueError("No combined result found for this run.")

        combined_content = (
            combined.get('combined_content')
            or combined.get('combinedContent')
            or ''
        )
        if not combined_content:
            raise ValueError("Combined content is empty.")

        root_id = 'root'
        root_doc = await self.get_combined_refinement_version(user_id, kapitel_id, run_id, root_id)
        if not root_doc:
            created_at = combined.get('created_at') or combined.get('createdAt') or SERVER_TIMESTAMP
            root_data = {
                'parent_version_id': None,
                'depth': 0,
                'user_message': None,
                'assistant_text': combined_content,
                'status': 'success',
                'model': combined.get('model_used') or combined.get('modelUsed') or '',
                'usage': {
                    'input_tokens': combined.get('input_tokens') or combined.get('inputTokens') or 0,
                    'cached_input_tokens': combined.get('cached_input_tokens') or combined.get('cachedInputTokens') or 0,
                    'output_tokens': combined.get('output_tokens') or combined.get('outputTokens') or 0,
                    'reasoning_tokens': combined.get('reasoning_tokens') or combined.get('reasoningTokens') or 0,
                    'total_tokens': combined.get('tokens_used') or combined.get('tokensUsed') or 0,
                },
                'cost': 0.0,
                'created_at': created_at,
            }
            await self.save_combined_refinement_version(user_id, kapitel_id, run_id, root_id, root_data)

        # Initialize refinement metadata on combined doc (merge, idempotent)
        combined_ref = self._combined_root_ref(user_id, kapitel_id, run_id)
        active_id = (
            combined.get('refinement_active_version_id')
            or combined.get('refinementActiveVersionId')
            or 'root'
        )
        combined_ref.set(
            {
                'refinement_root_version_id': 'root',
                'refinement_active_version_id': active_id,
                'refinement_cost_total': combined.get('refinement_cost_total') or combined.get('refinementCostTotal') or 0.0,
                'refinement_max_depth': max_depth,
                'refinement_initialized_at': SERVER_TIMESTAMP,
            },
            merge=True,
        )

        return {
            'root_version_id': 'root',
            'active_version_id': active_id,
            'max_depth': max_depth,
        }

    async def increment_combined_refinement_cost_total(
        self, user_id: str, kapitel_id: str, run_id: str, cost_usd: float
    ) -> None:
        """Increment combined/combined.refinement_cost_total atomically (USD)."""
        combined_ref = self._combined_root_ref(user_id, kapitel_id, run_id)
        combined_ref.update(
            {
                'refinement_cost_total': Increment(cost_usd),
                'refinement_updated_at': SERVER_TIMESTAMP,
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
            .collection('shortened')
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
        Ensure the refinement root version exists under shortened/shortened/versions/root.

        Also ensures shortened/shortened has refinement metadata fields initialized.
        """
        shortened = await self.get_shortened_result(user_id, kapitel_id, run_id)
        if not shortened:
            raise ValueError("No shortened result found for this run.")

        shortened_content = (
            shortened.get('shortened_content')
            or shortened.get('shortenedContent')
            or ''
        )
        if not shortened_content:
            raise ValueError("Shortened content is empty.")

        root_id = 'root'
        root_doc = await self.get_shortened_refinement_version(user_id, kapitel_id, run_id, root_id)
        if not root_doc:
            created_at = shortened.get('created_at') or shortened.get('createdAt') or SERVER_TIMESTAMP
            model = shortened.get('model') or ''

            tokens_used = shortened.get('tokens_used') or shortened.get('tokensUsed') or {}
            input_tokens = tokens_used.get('input') or tokens_used.get('prompt_tokens') or 0
            cached_input_tokens = (
                tokens_used.get('cached_input')
                or tokens_used.get('cachedInput')
                or tokens_used.get('cached_tokens')
                or 0
            )
            output_tokens = tokens_used.get('output') or tokens_used.get('completion_tokens') or 0
            total_tokens = int(input_tokens) + int(output_tokens)

            root_data = {
                'parent_version_id': None,
                'depth': 0,
                'user_message': None,
                'assistant_text': shortened_content,
                'status': 'success',
                'model': model,
                'usage': {
                    'input_tokens': int(input_tokens),
                    'cached_input_tokens': int(cached_input_tokens),
                    'output_tokens': int(output_tokens),
                    'reasoning_tokens': 0,
                    'total_tokens': total_tokens,
                },
                'cost': 0.0,
                'created_at': created_at,
            }
            await self.save_shortened_refinement_version(user_id, kapitel_id, run_id, root_id, root_data)

        # Initialize refinement metadata on shortened doc (merge, idempotent)
        shortened_ref = self._shortened_root_ref(user_id, kapitel_id, run_id)
        active_id = (
            shortened.get('refinement_active_version_id')
            or shortened.get('refinementActiveVersionId')
            or 'root'
        )
        shortened_ref.set(
            {
                'refinement_root_version_id': 'root',
                'refinement_active_version_id': active_id,
                'refinement_cost_total': shortened.get('refinement_cost_total') or shortened.get('refinementCostTotal') or 0.0,
                'refinement_max_depth': max_depth,
                'refinement_initialized_at': SERVER_TIMESTAMP,
            },
            merge=True,
        )

        return {
            'root_version_id': 'root',
            'active_version_id': active_id,
            'max_depth': max_depth,
        }

    async def increment_shortened_refinement_cost_total(
        self, user_id: str, kapitel_id: str, run_id: str, cost_usd: float
    ) -> None:
        """Increment shortened/shortened.refinement_cost_total atomically (USD)."""
        shortened_ref = self._shortened_root_ref(user_id, kapitel_id, run_id)
        shortened_ref.update(
            {
                'refinement_cost_total': Increment(cost_usd),
                'refinement_updated_at': SERVER_TIMESTAMP,
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
            .collection('lesefluss')
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
        Ensure the refinement root version exists under lesefluss/lesefluss/versions/root.

        Also ensures lesefluss/lesefluss has refinement metadata fields initialized.
        """
        lesefluss = await self.get_lesefluss_result(user_id, kapitel_id, run_id)
        if not lesefluss:
            raise ValueError("No lesefluss result found for this run.")

        lesefluss_content = (
            lesefluss.get('lesefluss_content')
            or lesefluss.get('leseflussContent')
            or ''
        )
        if not lesefluss_content:
            raise ValueError("Lesefluss content is empty.")

        root_id = 'root'
        root_doc = await self.get_lesefluss_refinement_version(user_id, kapitel_id, run_id, root_id)
        if not root_doc:
            created_at = lesefluss.get('created_at') or lesefluss.get('createdAt') or SERVER_TIMESTAMP
            model = lesefluss.get('model') or ''

            tokens_used = lesefluss.get('tokens_used') or lesefluss.get('tokensUsed') or {}
            input_tokens = tokens_used.get('input') or tokens_used.get('prompt_tokens') or 0
            cached_input_tokens = (
                tokens_used.get('cached_input')
                or tokens_used.get('cachedInput')
                or tokens_used.get('cached_tokens')
                or 0
            )
            output_tokens = tokens_used.get('output') or tokens_used.get('completion_tokens') or 0
            total_tokens = int(input_tokens) + int(output_tokens)

            root_data = {
                'parent_version_id': None,
                'depth': 0,
                'user_message': None,
                'assistant_text': lesefluss_content,
                'assistant_explanation': lesefluss.get('explanation') or '',
                'status': 'success',
                'model': model,
                'usage': {
                    'input_tokens': int(input_tokens),
                    'cached_input_tokens': int(cached_input_tokens),
                    'output_tokens': int(output_tokens),
                    'reasoning_tokens': 0,
                    'total_tokens': total_tokens,
                },
                'cost': 0.0,
                'created_at': created_at,
            }
            await self.save_lesefluss_refinement_version(user_id, kapitel_id, run_id, root_id, root_data)

        # Initialize refinement metadata on lesefluss doc (merge, idempotent)
        lesefluss_ref = self._lesefluss_root_ref(user_id, kapitel_id, run_id)
        active_id = (
            lesefluss.get('refinement_active_version_id')
            or lesefluss.get('refinementActiveVersionId')
            or 'root'
        )
        lesefluss_ref.set(
            {
                'refinement_root_version_id': 'root',
                'refinement_active_version_id': active_id,
                'refinement_cost_total': lesefluss.get('refinement_cost_total') or lesefluss.get('refinementCostTotal') or 0.0,
                'refinement_max_depth': max_depth,
                'refinement_initialized_at': SERVER_TIMESTAMP,
            },
            merge=True,
        )

        return {
            'root_version_id': 'root',
            'active_version_id': active_id,
            'max_depth': max_depth,
        }

    async def increment_lesefluss_refinement_cost_total(
        self, user_id: str, kapitel_id: str, run_id: str, cost_usd: float
    ) -> None:
        """Increment lesefluss/lesefluss.refinement_cost_total atomically (USD)."""
        lesefluss_ref = self._lesefluss_root_ref(user_id, kapitel_id, run_id)
        lesefluss_ref.update(
            {
                'refinement_cost_total': Increment(cost_usd),
                'refinement_updated_at': SERVER_TIMESTAMP,
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
        Save combined result under a run (separate collection next to results).
        """
        try:
            combined_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('combined')
                .document('combined')
            )

            combined_data = {
                'combined_content': combined_content,
                'source_quelle_ids': source_quelle_ids,
                'heading': heading,
                'topic': topic,
                'model_used': model_used,
                'tokens_used': tokens_used,
                'input_tokens': input_tokens,
                'cached_input_tokens': cached_input_tokens,
                'output_tokens': output_tokens,
                'reasoning_tokens': reasoning_tokens,
                'cost': cost,
                'created_at': SERVER_TIMESTAMP
            }

            if key_source:
                combined_data['key_source'] = key_source

            combined_ref.set(combined_data)
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
                .collection('intermediate_groups')
                .document(f'group_{group_number}')
            )

            group_data = {
                'group_number': group_number,
                'combined_content': combined_content,
                'source_quelle_ids': source_quelle_ids,
                'heading': heading,
                'topic': topic,
                'model_used': model_used,
                'tokens_used': tokens_used,
                'input_tokens': input_tokens,
                'cached_input_tokens': cached_input_tokens,
                'output_tokens': output_tokens,
                'reasoning_tokens': reasoning_tokens,
                'cost': cost,
                'created_at': SERVER_TIMESTAMP
            }

            if key_source:
                group_data['key_source'] = key_source

            group_ref.set(group_data)
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
        Fetch all intermediate group results for a run, ordered by group_number.
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
                .collection('intermediate_groups')
            )

            docs = groups_ref.stream()
            groups = []
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                groups.append(data)

            # Sort by group_number
            groups.sort(key=lambda x: x.get('group_number', 0))
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

    async def check_all_quellen_processed(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str
    ) -> tuple[bool, int]:
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
            result_ids = {r['id'] for r in results}

            # Check if all Quellen have results
            all_processed = all(quelle_id in result_ids for quelle_id in quelle_ids)

            # Count results with usable content
            content_count = sum(
                1 for r in results
                if r.get('has_content', True) and r.get('result_content')
            )

            logger.info(
                f"Kapitel {kapitel_id} run {run_id}: "
                f"{len(result_ids)}/{len(quelle_ids)} processed, "
                f"{content_count} with content"
            )

            return all_processed, content_count

        except Exception as e:
            logger.error(f"Error checking if all Quellen processed: {str(e)}")
            raise

    async def get_shortened_result(self, user_id: str, kapitel_id: str, run_id: str) -> Optional[dict]:
        """Fetch shortened result if it exists."""
        try:
            shortened_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('shortened')
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
        Save shortened result under a run.

        Args:
            shortened_data: Dict with shortenedContent, originalLength, shortenedLength,
                          usedKapitelIds, model, cost, tokensUsed, createdAt
        """
        try:
            shortened_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('shortened')
                .document('shortened')
            )

            shortened_ref.set(shortened_data)
            logger.info(
                f"Saved shortened result for kapitel {kapitel_id} run {run_id} "
                f"(cost: ${shortened_data.get('cost', 0)/100:.4f})"
            )
            return shortened_ref.id
        except Exception as e:
            logger.error(f"Error saving shortened result: {str(e)}")
            raise

    async def get_lesefluss_result(
        self, user_id: str, kapitel_id: str, run_id: str
    ) -> dict | None:
        """Get lesefluss result for a specific run."""
        try:
            doc_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('lesefluss')
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
        """Save lesefluss result to Firestore."""
        try:
            doc_ref = (
                self.db.collection('users')
                .document(user_id)
                .collection('kapitels')
                .document(kapitel_id)
                .collection('runs')
                .document(run_id)
                .collection('lesefluss')
                .document('lesefluss')
            )

            doc_ref.set(lesefluss_data)
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

        Args:
            summary_data: Dict with summaryContent, sourceKapitelId, sourceRunId,
                        sourceType, originalLength, summaryLength, model, cost,
                        tokensUsed, createdAt
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

            summary_ref.set(summary_data)
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
                "updated_at": SERVER_TIMESTAMP,
            }

            existing = secret_ref.get()
            if not existing.exists:
                payload["created_at"] = SERVER_TIMESTAMP

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
