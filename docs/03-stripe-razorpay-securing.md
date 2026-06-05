# Learning Module 03: Geographic Billing & Securing Webhooks (Stripe + Razorpay)

When building a public SaaS platform, you need to handle billing gateways. Often, you also need to support different gateways depending on geography (e.g. Stripe for global USD payments and Razorpay for domestic INR card/UPI flows).

However, exposing webhook endpoints to the public internet presents a massive security risk: **Webhook Spoofing**. An attacker could discover your webhook URL and send fake HTTP POST requests simulating a `"checkout.session.completed"` or `"payment.captured"` event, upgrading their quota limit for free.

This guide explains how to secure your Stripe and Razorpay webhook endpoints using **constant-time HMAC-SHA256 cryptographic signatures** in FastAPI.

---

## 🔒 Webhook Verification Threat Model

Without signature verification, your endpoint is unprotected:

```
[Attacker] ───( Fake HTTP POST checkout.completed )───> [FastAPI /webhook] ───( Upgrades Quota! )───> [DB]
```

To secure this, payment gateways sign the raw request body with a shared **webhook secret** (configured inside their merchant dashboard) and send this signature in the request headers. 

```
[Gateway] ───( Signed Payload + Header Sig )───> [FastAPI /webhook]
                                                     │
                                            (Verifies HMAC-SHA256)
                                                     │
                                           [YES: Update Quota DB]
                                           [NO: Return 401 Block]
```

---

## 🛠️ Cryptographic Verification: HMAC-SHA256

**HMAC** (Hash-based Message Authentication Code) combines a cryptographic hash function with a secret key. 

### 1. Stripe Signature Mechanics
Stripe sends the signature header in the format `t=timestamp,v1=sha256_signature`.
To verify it, we:
1.  Parse the timestamp `t` and signature hash `v1` from the header.
2.  Concatenate the timestamp string, a period `.`, and the **raw binary request body** bytes: `payload = timestamp + "." + raw_body`.
3.  Calculate the expected HMAC-SHA256 signature using the shared `STRIPE_WEBHOOK_SECRET` key.
4.  Compare the expected signature hash with `v1` in constant-time.

### 2. Preventing Timing Attacks
Why can't we use standard string comparison (`if signature == expected_sig`)?
Standard string comparisons stop checking as soon as they find a mismatch (character-by-character comparison). This leaks information about *how many* characters matched by measuring how long the comparison took (in nanoseconds). An attacker can run automated scripts to reconstruct your valid hash character-by-character (a **Timing Attack**).

To prevent this, we use `hmac.compare_digest()`, which performs comparison in **constant-time** regardless of where a mismatch occurs.

---

## 💻 Backend Implementation in FastAPI

Here is the signature verification code from `backend/billing_router.py`:

```python
import hmac
import hashlib
from fastapi import APIRouter, Request, Header, HTTPException, status

router = APIRouter()
STRIPE_SECRET = "whsec_mocksecret12345"

@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature")
):
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing signature header")

    # 1. Access the raw binary request body
    raw_body = await request.body()
    
    try:
        # 2. Parse Stripe header fields
        parts = {k: v for part in stripe_signature.split(',') for k, v in [part.split('=', 1)]}
        timestamp = parts.get('t')
        v1_hash = parts.get('v1')
        
        # 3. Recreate signed payload
        signed_payload = f"{timestamp}.".encode() + raw_body
        
        # 4. Compute expected HMAC hash
        expected_sig = hmac.new(
            STRIPE_SECRET.encode(),
            signed_payload,
            hashlib.sha256
        ).hexdigest()

        # 5. Constant-time secure comparison
        if not hmac.compare_digest(expected_sig, v1_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Signature mismatch"
            )
            
        # Process payment logic...
        return {"status": "success"}
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
```

---

## 🎯 Verification Exercise
1. Boot the FastAPI backend.
2. In the browser dashboard, click the "Stripe Checkout completed" and "Razorpay Payment Captured" buttons.
3. Review the terminal window logs: observe that the backend validates the signature, upgrades the plan to `PREMIUM`, and bumps subscription credits to `100 Runs`.
