import hashlib
import hmac


def sign(secret: str, event_id: int, action: str) -> str:
    msg = f"{action}:{event_id}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def verify(secret: str, event_id: int, action: str, sig: str) -> bool:
    return hmac.compare_digest(sign(secret, event_id, action), sig)
