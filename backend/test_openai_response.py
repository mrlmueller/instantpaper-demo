"""
Test script to check OpenAI API response structure and pricing
This will help verify we're capturing all tokens correctly
"""
import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from openai import AsyncOpenAI
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()

async def test_openai_response():
    """Test OpenAI API response to see the exact structure"""

    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("ERROR: OPENAI_API_KEY not found in environment")
        return

    client = AsyncOpenAI(api_key=api_key)

    # Test with a simple prompt
    test_prompt = "What is 2+2? Explain your reasoning step by step."

    print("=" * 80)
    print("Testing OpenAI Responses API")
    print("=" * 80)
    print(f"\nPrompt: {test_prompt}\n")

    # Test with different models
    models_to_test = [
        "gpt-4o-mini",
        # "gpt-4o",
        # "o1-mini",  # Uncomment if you have access
    ]

    for model in models_to_test:
        print(f"\n{'=' * 80}")
        print(f"Model: {model}")
        print(f"{'=' * 80}\n")

        try:
            response = await client.responses.create(
                model=model,
                input=[
                    {
                        "role": "system",
                        "content": "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
                    },
                    {
                        "role": "user",
                        "content": test_prompt
                    }
                ],
                reasoning={"effort": "high"},
                max_output_tokens=500
            )

            # Print the full response structure
            print("Full Response Object:")
            print("-" * 80)

            # Check what attributes the response has
            print(f"Response type: {type(response)}")
            print(f"Response attributes: {dir(response)}")
            print()

            # Print the model used
            if hasattr(response, 'model'):
                print(f"Model used: {response.model}")

            # Print usage information
            if hasattr(response, 'usage'):
                print(f"\nUsage object: {response.usage}")
                usage = response.usage

                print("\nToken breakdown:")
                print(f"  - Input tokens: {getattr(usage, 'input_tokens', 'N/A')}")
                print(f"  - Output tokens: {getattr(usage, 'output_tokens', 'N/A')}")
                print(f"  - Prompt tokens: {getattr(usage, 'prompt_tokens', 'N/A')}")
                print(f"  - Completion tokens: {getattr(usage, 'completion_tokens', 'N/A')}")

                # Check for reasoning tokens
                if hasattr(usage, 'completion_tokens_details'):
                    details = usage.completion_tokens_details
                    print(f"  - Completion tokens details: {details}")
                    if hasattr(details, 'reasoning_tokens'):
                        print(f"    * Reasoning tokens: {details.reasoning_tokens}")

                # Try to get total
                total = getattr(usage, 'total_tokens', None)
                if total:
                    print(f"  - Total tokens: {total}")

            # Print the output
            if hasattr(response, 'output_text'):
                print(f"\nOutput text: {response.output_text[:200]}...")
            elif hasattr(response, 'output'):
                print(f"\nOutput: {str(response.output)[:200]}...")

            # Try to print as dict/json if possible
            try:
                if hasattr(response, 'model_dump'):
                    print("\n" + "=" * 80)
                    print("Full Response as JSON:")
                    print("=" * 80)
                    print(json.dumps(response.model_dump(), indent=2))
            except Exception as e:
                print(f"\nCouldn't convert to JSON: {e}")

        except Exception as e:
            print(f"ERROR testing {model}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    print("\n🔍 OpenAI API Response Structure Test\n")
    asyncio.run(test_openai_response())
    print("\n✅ Test complete!\n")
