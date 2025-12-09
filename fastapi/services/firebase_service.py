import firebase_admin
from firebase_admin import credentials, auth, firestore
from google.cloud.firestore_v1 import SERVER_TIMESTAMP
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
        cost: float
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

            result_ref.set(result_data)
            logger.info(
                f"Saved result for quelle {quelle_id} in kapitel {kapitel_id} run {run_id} for user {user_id} "
                f"(cost: ${cost:.6f}, cached: {cached_input_tokens}, reasoning: {reasoning_tokens})"
            )

            return result_ref.id

        except Exception as e:
            logger.error(f"Error saving result: {str(e)}")
            raise

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
        cost: float
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

            combined_ref.set(combined_data)
            logger.info(
                f"Saved combined result for kapitel {kapitel_id} run {run_id} (cost: ${cost:.6f})"
            )
            return combined_ref.id
        except Exception as e:
            logger.error(f"Error saving combined result: {str(e)}")
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


# Create singleton instance
firebase_service = FirebaseService()
