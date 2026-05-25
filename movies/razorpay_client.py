"""
Razorpay API client — zero external dependencies.

Uses only Python's built-in urllib and hmac/hashlib so no pip install
is required. Handles order creation, payment fetching, and both kinds
of signature verification (checkout callback + server webhook).
"""
import base64
import hashlib
import hmac
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)

RAZORPAY_BASE_URL = 'https://api.razorpay.com/v1'


class RazorpayError(Exception):
    """Raised when the Razorpay API returns an error or the network fails."""


class RazorpayClient:
    """
    Thin wrapper around the Razorpay REST API.
    All requests use HTTP Basic Auth (key_id:key_secret).
    """

    def __init__(self):
        self.key_id = settings.RAZORPAY_KEY_ID
        self.key_secret = settings.RAZORPAY_KEY_SECRET
        creds = base64.b64encode(
            f'{self.key_id}:{self.key_secret}'.encode()
        ).decode()
        self._auth_header = f'Basic {creds}'

    # ── Internal HTTP helper ──────────────────────────────────────────────────

    def _request(self, method: str, endpoint: str, data: dict = None) -> dict:
        url = f'{RAZORPAY_BASE_URL}{endpoint}'
        body = json.dumps(data).encode('utf-8') if data else None
        req = Request(url, data=body, method=method)
        req.add_header('Authorization', self._auth_header)
        req.add_header('Content-Type', 'application/json')
        req.add_header('Accept', 'application/json')

        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except HTTPError as exc:
            try:
                err = json.loads(exc.read()).get('error', {})
                msg = err.get('description', str(exc))
            except Exception:
                msg = str(exc)
            logger.error('Razorpay API error %s %s: %s', method, endpoint, msg)
            raise RazorpayError(msg) from exc
        except URLError as exc:
            logger.error('Razorpay network error: %s', exc.reason)
            raise RazorpayError(f'Network error reaching Razorpay: {exc.reason}') from exc

    # ── Public API methods ────────────────────────────────────────────────────

    def create_order(self, amount_paise: int, currency: str = 'INR',
                     receipt: str = '', notes: dict = None) -> dict:
        """
        Create a Razorpay order. Returns the full order object.
        amount_paise: amount in paise (1 INR = 100 paise).
        receipt: our internal reference (booking_ref).
        """
        return self._request('POST', '/orders', {
            'amount': amount_paise,
            'currency': currency,
            'receipt': receipt,
            'notes': notes or {},
        })

    def fetch_payment(self, payment_id: str) -> dict:
        """Fetch a payment by its Razorpay payment ID."""
        return self._request('GET', f'/payments/{payment_id}')

    # ── Signature verification (no network call needed) ───────────────────────

    def verify_payment_signature(self, order_id: str, payment_id: str,
                                  signature: str) -> bool:
        """
        Verifies the HMAC-SHA256 signature returned by Razorpay checkout.

        Security: we use hmac.compare_digest (constant-time comparison) to
        prevent timing attacks. The secret never leaves the server — only
        its HMAC output is compared against the value from the client.

        Fraud / replay prevention: the signature binds order_id + payment_id
        together, so replaying a signature from a different transaction fails.
        """
        message = f'{order_id}|{payment_id}'.encode('utf-8')
        expected = hmac.new(
            self.key_secret.encode('utf-8'),
            message,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        """
        Verifies the HMAC-SHA256 signature on an incoming webhook request.

        Uses settings.RAZORPAY_WEBHOOK_SECRET (separate from the API secret).
        raw_body must be the exact bytes of the request body before any parsing,
        otherwise the HMAC will not match.

        Replay attack mitigation: Razorpay includes a unique event_id in every
        webhook payload. We persist this in the DB and reject any duplicate
        event_id, so even a valid re-delivered webhook is a no-op.
        """
        webhook_secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '')
        if not webhook_secret:
            logger.warning('RAZORPAY_WEBHOOK_SECRET is not set — webhook verification skipped.')
            return False
        expected = hmac.new(
            webhook_secret.encode('utf-8'),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


# Module-level singleton — import this everywhere.
razorpay_client = RazorpayClient()
