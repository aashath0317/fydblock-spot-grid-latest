from cryptography.fernet import Fernet
from config import ENCRYPTION_KEY
from utils.logger import setup_logger

logger = setup_logger("security")


def get_or_create_key():
    """
    Retrieves the encryption key from config/env.
    STRICTLY requires ENCRYPTION_KEY to be set.
    """
    key = ENCRYPTION_KEY

    if not key:
        logger.critical("No ENCRYPTION_KEY found in environment variables.")
        raise ValueError(
            "CRITICAL: ENCRYPTION_KEY is missing. "
            "You MUST set this environment variable for security. "
            "Do not rely on auto-generation in production."
        )

    return key


# Initialize Fernet
try:
    _key = get_or_create_key()
    cipher_suite = Fernet(_key)
except Exception as e:
    logger.critical(f"Failed to initialize encryption: {e}")
    raise


def encrypt_value(value: str) -> str:
    """Encrypts a string value and returns it as a base64 encoded string."""
    if not value:
        return value
    try:
        encrypted_bytes = cipher_suite.encrypt(value.encode())
        return encrypted_bytes.decode()  # Store as string
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise


def decrypt_value(token: str) -> str:
    """Decrypts a base64 encoded string token."""
    if not token:
        return token
    try:
        decrypted_bytes = cipher_suite.decrypt(token.encode())
        return decrypted_bytes.decode()
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        raise
