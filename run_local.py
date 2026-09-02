#!/usr/bin/env python3
"""
Local development runner for testing the bot
This uses polling instead of webhook, so it's only for local development
"""
import asyncio
import logging
import sys

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def main():
    """Run the bot in polling mode for local development"""
    try:
        logger.info("🚀 Starting Telegram bot in polling mode (LOCAL DEVELOPMENT)")
        logger.info("⚠️  Note: This uses polling, not webhook. Only for development!")

        import database as db
        from app import create_application

        # Initialize database
        logger.info("Initializing database...")
        db.init_db()
        logger.info("✅ Database initialized")

        # Create and configure application
        logger.info("Creating Telegram application...")
        app = create_application()
        logger.info("✅ Application created")

        # Start polling
        logger.info("Starting polling...")
        logger.info("📱 Bot is running! Send messages to test.")
        logger.info("Press Ctrl+C to stop")

        async with app:
            await app.start()
            await app.updater.start_polling(allowed_updates=["message", "callback_query"])

            # Keep running
            await asyncio.Event().wait()

    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"💥 Critical error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
        sys.exit(0)
