import firebase_admin
from firebase_admin import credentials, auth, firestore
from google.cloud.firestore_v1 import SERVER_TIMESTAMP
from utils.config import config
import logging
from typing import Optional, Tuple

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
