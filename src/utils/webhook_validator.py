"""
GitHub webhook signature validation utilities
"""

import hashlib
import hmac
import structlog

logger = structlog.get_logger()


def validate_github_webhook(payload: bytes, signature: str, secret: str) -> bool:
    """
    Validate GitHub webhook signature

    Args:
        payload: Raw request body as bytes
        signature: X-Hub-Signature-256 header value
        secret: Webhook secret configured in GitHub

    Returns:
        bool: True if signature is valid, False otherwise
    """
    if not signature.startswith("sha256="):
        logger.warning("Invalid signature format", signature=signature)
        return False

    # Extract the signature hash
    signature_hash = signature[7:]  # Remove "sha256=" prefix

    # Compute expected signature
    expected_signature = hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()

    # Use constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(signature_hash, expected_signature)

    if not is_valid:
        logger.warning(
            "Invalid webhook signature",
            expected_prefix=expected_signature[:8],
            received_prefix=signature_hash[:8],
        )

    return is_valid


def extract_github_event_type(headers: dict) -> str:
    """
    Extract GitHub event type from webhook headers

    Args:
        headers: Request headers dict

    Returns:
        str: Event type (e.g., 'issues', 'pull_request')
    """
    return headers.get("X-GitHub-Event", "unknown")
