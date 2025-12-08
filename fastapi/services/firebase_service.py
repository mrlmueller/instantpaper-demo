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

    async def get_paper(self, user_id: str, paper_id: str) -> Optional[dict]:
        """
        Fetch a paper from Firestore

        Args:
            user_id: User ID (owner of the paper)
            paper_id: Paper document ID

        Returns:
            dict: Paper data if found, None otherwise
        """
        try:
            doc_ref = self.db.collection('users').document(user_id) \
                            .collection('papers').document(paper_id)
            doc = doc_ref.get()

            if doc.exists:
                return doc.to_dict()
            else:
                logger.warning(f"Paper {paper_id} not found for user {user_id}")
                return None

        except Exception as e:
            logger.error(f"Error fetching paper: {str(e)}")
            raise

    async def save_result(
        self,
        user_id: str,
        paper_id: str,
        user_input: str,
        result_content: str,
        model_used: str,
        tokens_used: int
    ) -> str:
        """
        Save AI processing result to Firestore

        Args:
            user_id: User ID
            paper_id: Source paper ID
            user_input: User's instructions
            result_content: AI-generated content
            model_used: OpenAI model used
            tokens_used: Number of tokens consumed

        Returns:
            str: Result document ID
        """
        try:
            # Create result document
            result_ref = self.db.collection('users').document(user_id) \
                                .collection('results').document()

            result_data = {
                'paper_id': paper_id,
                'user_input': user_input,
                'result_content': result_content,
                'model_used': model_used,
                'tokens_used': tokens_used,
                'created_at': SERVER_TIMESTAMP
            }

            result_ref.set(result_data)
            logger.info(f"Saved result {result_ref.id} for user {user_id}")

            return result_ref.id

        except Exception as e:
            logger.error(f"Error saving result: {str(e)}")
            raise


# Create singleton instance
firebase_service = FirebaseService()
