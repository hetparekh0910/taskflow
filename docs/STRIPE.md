# Stripe setup (test mode) — step by step

You do **not** need a business or a bank account for test mode. No real money moves.
Until you finish this, the app runs in **mock mode** (a fake checkout page) and everything still demos.

## 1. Create the account and get your test key
1. Sign up at https://dashboard.stripe.com/register (skip the "activate account" steps).
2. Make sure the **Test mode** toggle (top right) is on.
3. Developers → **API keys** → copy the **Secret key** (`sk_test_...`). Never commit it.

## 2. Create the Pro and Business prices (one command)
```powershell
cd backend
.venv\Scripts\activate
$env:STRIPE_SECRET_KEY="sk_test_PASTE_HERE"
python scripts\stripe_setup.py
```
It prints `STRIPE_PRICE_PRO=price_...` and `STRIPE_PRICE_BUSINESS=price_...`. (Re-running is safe.)

## 3. Turn on the Customer Portal (once)
Settings → Billing → **Customer portal** → click **Save** (defaults are fine). Without this the "Manage billing" button errors.

## 4. Local webhooks with the Stripe CLI
```powershell
winget install Stripe.StripeCli
stripe login
stripe listen --forward-to localhost:8000/api/billing/stripe-webhook/
```
It prints `whsec_...`. Use the port your Django server really runs on.
(The upgrade also happens without this: after paying, the billing page calls `/billing/sync/` to pull the plan from Stripe. The webhook keeps it in sync for renewals, failed payments and cancellations.)

## 5. Run the backend with the keys
```powershell
$env:STRIPE_SECRET_KEY="sk_test_..."
$env:STRIPE_PRICE_PRO="price_..."
$env:STRIPE_PRICE_BUSINESS="price_..."
$env:STRIPE_WEBHOOK_SECRET="whsec_..."
python manage.py runserver
```
Billing page → Upgrade → pay with card **4242 4242 4242 4242**, any future date, any CVC. You return to the app on the new plan.
Other test cards: `4000 0000 0000 0341` (attaches, then payment fails), `4000 0000 0000 9995` (declined).

## 6. Production (Render)
1. Render → your API service → Environment: add the four variables above plus `FRONTEND_URL=https://<your-app>.vercel.app`.
2. Stripe → Developers → **Webhooks** → Add endpoint: `https://<api>.onrender.com/api/billing/stripe-webhook/`, events
   `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`.
3. Copy that endpoint's **Signing secret** into `STRIPE_WEBHOOK_SECRET` on Render (it differs from the CLI's one).

## Troubleshooting
- "No Stripe price configured" → `STRIPE_PRICE_*` not set in the *backend's* environment.
- Portal error → step 3 not saved.
- Webhook 400 → wrong `whsec_` (CLI vs dashboard secret) or the body was altered by a proxy.
- Still on Free after paying → open the billing page once (it syncs), check the backend log.
