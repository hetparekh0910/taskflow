"""Create the TaskFlow products and monthly prices in your Stripe TEST account (safe to re-run).

    cd backend
    STRIPE_SECRET_KEY=sk_test_xxx python scripts/stripe_setup.py        # macOS/Linux
    $env:STRIPE_SECRET_KEY="sk_test_xxx"; python scripts/stripe_setup.py  # Windows PowerShell

Prints the STRIPE_PRICE_PRO / STRIPE_PRICE_BUSINESS lines to paste into your environment.
Prices are found by `lookup_key`, so running it twice does not create duplicates.
"""
import os
import sys

PLANS = {"pro": ("TaskFlow Pro", 1200), "business": ("TaskFlow Business", 4900)}


def ensure_prices(stripe):
    out = {}
    for key, (name, cents) in PLANS.items():
        lookup = f"taskflow_{key}_monthly"
        found = stripe.Price.list(lookup_keys=[lookup], limit=1).get("data", [])
        if found:
            out[key] = found[0]["id"]
            continue
        product = stripe.Product.create(name=name, metadata={"plan": key})
        price = stripe.Price.create(
            product=product["id"], unit_amount=cents, currency="usd",
            recurring={"interval": "month"}, lookup_key=lookup, metadata={"plan": key},
        )
        out[key] = price["id"]
    return out


def main():
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key.startswith("sk_test_"):
        sys.exit("Set STRIPE_SECRET_KEY to your TEST key (starts with sk_test_). Refusing to run with a live key.")
    import stripe

    stripe.api_key = key
    prices = ensure_prices(stripe)
    print("\nAdd these to your environment (.env or Render):\n")
    print(f"STRIPE_PRICE_PRO={prices['pro']}")
    print(f"STRIPE_PRICE_BUSINESS={prices['business']}\n")


if __name__ == "__main__":
    main()
