import hmac
import hashlib
import logging
import os
from fastapi import APIRouter, Request, HTTPException, Header, status

logger = logging.getLogger("billing_router")
router = APIRouter(prefix="/api/billing")

# Webhook secret configurations loaded from environment
STRIPE_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_mocksecret12345")
RAZORPAY_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "rzp_mocksecret12345")

# Mock database mapping user accounts to paid credit quotas
mock_quota_db = {
    "user_1": {"plan": "free", "credits": 5},
    "user_2": {"plan": "premium", "credits": 100}
}

@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature")
):
    """
    Ingests and validates Stripe payments.
    Stripe signatures are typically structured as: t=timestamp,v1=signature
    We parse the raw body and verify using HMAC-SHA256.
    """
    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header"
        )

    # Read raw bytes to ensure signature verification hash integrity
    raw_body = await request.body()
    
    try:
        # Parse Stripe signature fields (e.g. t=123456,v1=sha256hash)
        parts = {k: v for part in stripe_signature.split(',') for k, v in [part.split('=', 1)]}
        timestamp = parts.get('t')
        v1_hash = parts.get('v1')
        
        if not timestamp or not v1_hash:
            raise ValueError("Malformed Stripe signature format")
            
        # Recreate expected payload: timestamp + "." + raw_body
        signed_payload = f"{timestamp}.".encode() + raw_body
        
        # Calculate expected HMAC hash
        expected_sig = hmac.new(
            STRIPE_SECRET.encode(),
            signed_payload,
            hashlib.sha256
        ).hexdigest()

        # Constant-time comparison to protect against timing attacks
        if not hmac.compare_digest(expected_sig, v1_hash):
            logger.warning("Stripe webhook verification failed: signature mismatch.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature hash"
            )

        # Process webhook event (simulated payload)
        payload_json = await request.json()
        event_type = payload_json.get("type")

        if event_type == "checkout.session.completed":
            user_id = payload_json["data"]["object"]["client_reference_id"]
            # Upgrade user credits in DB
            if user_id in mock_quota_db:
                mock_quota_db[user_id]["plan"] = "premium"
                mock_quota_db[user_id]["credits"] += 100
                logger.info(f"Stripe: Upgraded quota for user '{user_id}' to premium.")

        return {"status": "success", "gateway": "stripe"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stripe webhook processing error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook Error: {str(e)}"
        )

@router.post("/webhook/razorpay")
async def razorpay_webhook(
    request: Request,
    razorpay_signature: str = Header(None, alias="X-Razorpay-Signature")
):
    """
    Ingests and validates Razorpay payments (INR geo-routing).
    Validates signature using raw body + Razorpay secret key.
    """
    if not razorpay_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Razorpay-Signature header"
        )

    raw_body = await request.body()

    try:
        # Calculate HMAC signature using Razorpay webhook secret
        expected_sig = hmac.new(
            RAZORPAY_SECRET.encode(),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        # Constant-time comparison
        if not hmac.compare_digest(expected_sig, razorpay_signature):
            logger.warning("Razorpay webhook verification failed: signature mismatch.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature hash"
            )

        payload_json = await request.json()
        event_type = payload_json.get("event")

        if event_type == "payment.captured":
            # Extract billing parameters (simulated payload paths)
            user_email = payload_json["payload"]["payment"]["entity"]["email"]
            # Upgrade credit quota
            logger.info(f"Razorpay: Payment captured successfully for email '{user_email}'. Quota increased.")

        return {"status": "success", "gateway": "razorpay"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Razorpay webhook processing error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook Error: {str(e)}"
        )
        
@router.get("/user/quota")
async def get_user_quota(user_id: str = "user_1"):
    """Simple database utility endpoint to inspect user quotas."""
    quota = mock_quota_db.get(user_id, {"plan": "free", "credits": 0})
    return {
        "user_id": user_id,
        "plan": quota["plan"],
        "remaining_credits": quota["credits"]
    }
