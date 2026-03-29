"""
Test script to verify OpenAI API token usage and cost calculation.

This script will:
1. Make a real API call to OpenAI
2. Show the exact token structure returned
3. Verify the model name (including release suffixes)
4. Calculate costs manually to verify correctness
"""
import asyncio
import os
import re
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from openai import AsyncOpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Pricing per million tokens (input, output)
MODEL_PRICING = {
    "gpt-5.2": (1.75, 14.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
}


def resolve_pricing_key(model_name: str):
    """Normalize returned model names (handles release date suffixes)."""
    model_lower = (model_name or "").lower()
    normalized_keys = {key.lower(): key for key in MODEL_PRICING}

    if model_lower in normalized_keys:
        return normalized_keys[model_lower]

    date_stripped = re.sub(r"-20\d{2}-\d{2}-\d{2}$", "", model_lower)
    if date_stripped in normalized_keys:
        return normalized_keys[date_stripped]

    for key_lower, original in normalized_keys.items():
        if model_lower.startswith(f"{key_lower}-"):
            return original

    return None


async def test_cost_calculation():
    """Test OpenAI API response and cost calculation"""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("WARNING  ERROR: OPENAI_API_KEY not found in .env file")
        return

    client = AsyncOpenAI(api_key=api_key)

    # Very short test prompt to minimize cost
    test_prompt = "Say 'Hello' in one word."

    print("=" * 80)
    print("OpenAI API Cost Calculation Test")
    print("=" * 80)
    print(f"\nTest Prompt: {test_prompt}")
    print("Expected: Very low cost due to minimal tokens\n")

    # Test each model
    models_to_test = ["gpt-5-nano", "gpt-5-mini", "gpt-5.2", "gpt-5.2-2025-11-13"]

    for model in models_to_test:
        print(f"\n{'=' * 80}")
        print(f"Testing Model: {model}")
        print(f"{'=' * 80}")

        try:
            response = await client.responses.create(
                model=model,
                input=[
                    {
                        "role": "user",
                        "content": test_prompt,
                    }
                ],
                reasoning={"effort": "high"},
                max_output_tokens=50,  # Limit to reduce cost
            )

            # Extract usage data
            usage = response.usage if hasattr(response, "usage") else None
            if not usage:
                print("? No usage data in response!")
                continue

            # Extract tokens
            input_tokens = (
                getattr(usage, "input_tokens", None)
                or getattr(usage, "prompt_tokens", 0)
                or 0
            )
            output_tokens = (
                getattr(usage, "output_tokens", None)
                or getattr(usage, "completion_tokens", 0)
                or 0
            )

            # Extract reasoning tokens
            reasoning_tokens = 0
            completion_details = getattr(usage, "completion_tokens_details", None)
            if completion_details:
                reasoning_tokens = getattr(completion_details, "reasoning_tokens", 0) or 0

            total_tokens = input_tokens + output_tokens + reasoning_tokens

            # Get actual model name returned
            actual_model = getattr(response, "model", "unknown")

            print("\nResponse Details:")
            print(f"  Model Requested: {model}")
            print(f"  Model Returned:  {actual_model}")
            print("\nToken Usage:")
            print(f"  Input Tokens:      {input_tokens:,}")
            print(f"  Output Tokens:     {output_tokens:,}")
            print(f"  Reasoning Tokens:  {reasoning_tokens:,}")
            print(f"  {'=' * 40}")
            print(f"  Total Tokens:      {total_tokens:,}")

            # Calculate cost using the CORRECT model name
            pricing_key = resolve_pricing_key(actual_model)
            if pricing_key:
                pricing = MODEL_PRICING[pricing_key]
            else:
                print(f"\nWARNING  WARNING: Model '{actual_model}' not found in pricing dictionary!")
                print(f"  Available models: {list(MODEL_PRICING.keys())}")
                print("  Using fallback pricing for gpt-5-mini")
                pricing = MODEL_PRICING["gpt-5-mini"]

            input_price, output_price = pricing

            # Calculate cost (reasoning tokens charged at output rate)
            input_cost = (input_tokens / 1_000_000) * input_price
            total_output_tokens = output_tokens + reasoning_tokens
            output_cost = (total_output_tokens / 1_000_000) * output_price
            total_cost = input_cost + output_cost

            print("\nCost Calculation:")
            print(f"  Pricing: ${input_price}/M input, ${output_price}/M output")
            print(
                f"  Input Cost:   ${input_cost:.6f} ({input_tokens:,} x ${input_price}/M)"
            )
            print(
                f"  Output Cost:  ${output_cost:.6f} ({output_tokens:,} + {reasoning_tokens:,} reasoning x ${output_price}/M)"
            )
            print(f"  {'=' * 40}")
            print(f"  Total Cost:   ${total_cost:.6f}")

            # Get output text
            if hasattr(response, "output_text"):
                output_text = response.output_text
            elif hasattr(response, "output"):
                try:
                    output_text = response.output[0].content[0].text
                except Exception:
                    output_text = str(response.output)[:100]
            else:
                output_text = "Unable to extract output"

            print("\nResponse Text:")
            print(f"  {output_text[:200]}")

        except Exception as e:
            print(f"? ERROR testing {model}: {e}")
            import traceback

            traceback.print_exc()

    print("\n" + "=" * 80)
    print("Test Complete!")
    print("=" * 80)
    print("\nKey Takeaways:")
    print("  1. Check if 'Model Returned' matches 'Model Requested'")
    print("  2. Verify reasoning tokens are being extracted")
    print("  3. Confirm costs are calculated correctly")
    print("  4. Compare with OpenAI dashboard to validate\n")


if __name__ == "__main__":
    asyncio.run(test_cost_calculation())
