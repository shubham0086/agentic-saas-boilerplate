import crypto from 'crypto';

const BACKEND_URL = "http://localhost:8000";
const STRIPE_SECRET = "whsec_mocksecret12345";
const RAZORPAY_SECRET = "rzp_mocksecret12345";

async function simulateStripeWebhook() {
  console.log("Generating valid Stripe checkout.session.completed event...");

  const payload = {
    type: "checkout.session.completed",
    data: {
      object: {
        client_reference_id: "user_1"
      }
    }
  };

  const rawBody = JSON.stringify(payload);
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const signedPayload = timestamp + "." + rawBody;

  // Calculate HMAC-SHA256 signature
  const v1Hash = crypto
    .createHmac('sha256', STRIPE_SECRET)
    .update(signedPayload)
    .digest('hex');

  const stripeSignature = `t=${timestamp},v1=${v1Hash}`;

  try {
    const res = await fetch(`${BACKEND_URL}/api/billing/webhook/stripe`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Stripe-Signature": stripeSignature
      },
      body: rawBody
    });

    const data = await res.json();
    console.log(`[Stripe Simulation] Response:`, data);
  } catch (err) {
    console.error(`[Stripe Simulation] Failed:`, err.message);
  }
}

async function simulateRazorpayWebhook() {
  console.log("Generating valid Razorpay payment.captured event...");

  const payload = {
    event: "payment.captured",
    payload: {
      payment: {
        entity: {
          email: "user_1@example.com"
        }
      }
    }
  };

  const rawBody = JSON.stringify(payload);

  // Calculate HMAC-SHA256 signature
  const signature = crypto
    .createHmac('sha256', RAZORPAY_SECRET)
    .update(rawBody)
    .digest('hex');

  try {
    const res = await fetch(`${BACKEND_URL}/api/billing/webhook/razorpay`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": signature
      },
      body: rawBody
    });

    const data = await res.json();
    console.log(`[Razorpay Simulation] Response:`, data);
  } catch (err) {
    console.error(`[Razorpay Simulation] Failed:`, err.message);
  }
}

async function run() {
  console.log("🚀 Starting SaaS Webhook Simulation Runner...");
  await simulateStripeWebhook();
  console.log("-----------------------------------------");
  await simulateRazorpayWebhook();
  console.log("🏁 Webhook simulations complete. Check your FastAPI console output to verify quota updates!");
}

run();
