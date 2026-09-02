"""WSGI application entry point for PythonAnywhere"""
import os
import sys
import logging

# Setup path
path = os.path.dirname(os.path.abspath(__file__))
if path not in sys.path:
    sys.path.insert(0, path)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from app import app, create_application, telegram_app

    # Create telegram application on startup
    if telegram_app is None:
        logger.info("Initializing Telegram application...")
        create_application()

    logger.info("✅ WSGI app loaded successfully")
except Exception as e:
    logger.error(f"❌ Failed to load WSGI app: {e}")
    raise
