"""
Simple verification of cost calculation fixes (no API calls).
"""

import re

# Pricing per million tokens (input, output)
MODEL_PRICING = {
    "gpt-5.4": (2.50, 15.00),  # Current top-tier model
    "gpt-5.2": (1.75, 14.00),  # Most expensive model
    "gpt-5-mini": (0.25, 2.00),  # Mid-tier model
    "gpt-5-nano": (0.05, 0.40),  # Most economical model
}


def resolve_model_key(model_name: str):
    """
    Normalize model names that include release suffixes (e.g., gpt-5.4-2026-03-05).
    Mirrors the production cost calculation logic.
    """
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


def calculate_test_cost(model, input_tokens, output_tokens, reasoning_tokens):
    """Calculate cost for testing"""
    pricing_key = resolve_model_key(model)
    if pricing_key:
        pricing = MODEL_PRICING[pricing_key]
    else:
        print(f"  WARNING: Model '{model}' not found, using gpt-5-mini fallback")
        pricing = MODEL_PRICING["gpt-5-mini"]

    input_price, output_price = pricing

    input_cost = (input_tokens / 1_000_000) * input_price
    total_output_tokens = output_tokens + reasoning_tokens
    output_cost = (total_output_tokens / 1_000_000) * output_price
    total_cost = input_cost + output_cost

    return total_cost


print("=" * 80)
print("Cost Calculation Fix Verification")
print("=" * 80)

# Test 1: Model Matching
print("\nTest 1: Model Name Matching")
print("-" * 80)

test_models = [
    "gpt-5.4",
    "gpt-5.2",
    "gpt-5-mini",
    "gpt-5-nano",
    "GPT-5.4",
    "gpt-5.4-2026-03-05",
    "gpt-4o",
    "unknown",
]
for model in test_models:
    match = resolve_model_key(model)
    if match:
        print(f"  - '{model}' -> Matched: '{match}'")
    else:
        print(f"  - '{model}' -> No match (will use fallback)")

# Test 2: Cost Calculation
print("\nTest 2: Cost Calculation")
print("-" * 80)
print("Sample scenario: 1000 input, 500 output, 2000 reasoning tokens\n")

for model in ["gpt-5.4", "gpt-5-mini", "gpt-5-nano"]:
    cost = calculate_test_cost(model, 1000, 500, 2000)
    pricing = MODEL_PRICING[model]
    print(f"  {model}:")
    print(f"    Pricing: ${pricing[0]}/M input, ${pricing[1]}/M output")
    print(f"    Cost: ${cost:.6f}")
    print()

# Test 3: Relative Cost Comparison
print("\nTest 3: Relative Cost Comparison")
print("-" * 80)

cost_5_4 = calculate_test_cost("gpt-5.4", 1000, 500, 2000)
cost_5_mini = calculate_test_cost("gpt-5-mini", 1000, 500, 2000)
cost_5_nano = calculate_test_cost("gpt-5-nano", 1000, 500, 2000)

print(f"  gpt-5.4:    ${cost_5_4:.6f}")
print(f"  gpt-5-mini: ${cost_5_mini:.6f}")
print(f"  gpt-5-nano: ${cost_5_nano:.6f}")
print()

ratio_5_4_to_nano = cost_5_4 / cost_5_nano
ratio_5_4_to_mini = cost_5_4 / cost_5_mini
ratio_5_mini_to_nano = cost_5_mini / cost_5_nano

print("  Ratios:")
print(f"    gpt-5.4 / gpt-5-nano = {ratio_5_4_to_nano:.1f}x (expected: ~38x)")
print(f"    gpt-5.4 / gpt-5-mini = {ratio_5_4_to_mini:.1f}x (expected: ~7.6x)")
print(f"    gpt-5-mini / gpt-5-nano = {ratio_5_mini_to_nano:.1f}x (expected: ~5x)")

print("\n" + "=" * 80)
print("Verification Complete!")
print("=" * 80)
print("\nNext Steps:")
print("  1. Restart your FastAPI server to load the changes")
print("  2. Process a Kapitel with different models")
print("  3. Check the logs for 'Matching model' and 'Matched pricing key' messages")
print("  4. Verify costs now match OpenAI dashboard\n")
