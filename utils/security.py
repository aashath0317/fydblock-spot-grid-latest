from cryptography.fernet import Fernet
from config import BASE_DIR, ENCRYPTION_KEY
from utils.logger import setup_logger

logger = setup_logger("security")


def get_or_create_key():
    """
    Retrieves the encryption key from config/env, or generates a new one
    and saves it to .env if it doesn't exist.
    """
    key = ENCRYPTION_KEY

    if not key:
        logger.warning("No ENCRYPTION_KEY found. Generating a new one...")
        key = Fernet.generate_key().decode()

        # Save to .env
        env_path = BASE_DIR / ".env"
        try:
            with open(env_path, "a") as f:
                f.write(f"\nENCRYPTION_KEY={key}\n")
            logger.info(f"New ENCRYPTION_KEY saved to {env_path}")
        except Exception as e:
            logger.error(f"Failed to save ENCRYPTION_KEY to .env: {e}")
            # If we can't save it, we might want to panic, but for now return it
            # so the app works (temporarily).

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
