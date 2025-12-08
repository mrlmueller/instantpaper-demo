from fastapi import HTTPException
from services.firebase_service import firebase_service
from services.openai_service import openai_service
import logging

logger = logging.getLogger(__name__)


class PaperService:
    """Service for paper processing operations"""

    def __init__(self):
        """Initialize paper service"""
        self.firebase = firebase_service
        self.openai = openai_service
        logger.info("Paper service initialized")

    async def process_single_paper(
        self,
        user_id: str,
        paper_id: str,
        user_input: str,
        model: str
    ) -> dict:
        """
        Process a single paper with OpenAI

        Args:
            user_id: ID of the user making the request
            paper_id: ID of the paper to process
            user_input: User instructions for processing
            model: OpenAI model to use

        Returns:
            dict: Processing result with content, tokens, model, and result_id

        Raises:
            HTTPException: 404 if paper not found
        """
        try:
            # Step 1: Fetch paper from Firestore (verifies ownership)
            logger.info(f"Fetching paper {paper_id} for user {user_id}")
            paper = await self.firebase.get_paper(user_id, paper_id)

            if not paper:
                logger.warning(f"Paper {paper_id} not found for user {user_id}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Paper {paper_id} not found or you don't have access to it"
                )

            # Step 2: Process with OpenAI
            logger.info(f"Processing paper {paper_id} with OpenAI model {model}")
            openai_result = await self.openai.process_paper(
                paper['content'],
                user_input,
                model
            )

            # Step 3: Save result to Firestore
            logger.info(f"Saving result for paper {paper_id}")
            result_id = await self.firebase.save_result(
                user_id=user_id,
                paper_id=paper_id,
                user_input=user_input,
                result_content=openai_result['content'],
                model_used=openai_result['model'],
                tokens_used=openai_result['tokens']
            )

            logger.info(f"Paper processing complete. Result ID: {result_id}")

            return {
                "result_id": result_id,
                "content": openai_result['content'],
                "model": openai_result['model'],
                "tokens": openai_result['tokens']
            }

        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            logger.error(f"Error processing paper: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process paper: {str(e)}"
            )


# Create singleton instance
paper_service = PaperService()
