#!/usr/bin/env python3
"""Setup webhook for Telegram bot"""
import requests
import logging
from config import BOT_TOKEN, WEBHOOK_URL

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def setup_webhook():
    """Set up webhook for Telegram bot"""
    try:
        logger.info(f"🔗 Setting webhook to: {WEBHOOK_URL}")

        # Set webhook
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        data = {"url": WEBHOOK_URL}
        response = requests.post(url, data=data, timeout=10)
        result = response.json()

        if result.get('ok'):
            logger.info("✅ Webhook установлен успешно!")

            # Get webhook info
            check_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
            check_response = requests.get(check_url, timeout=10)
            webhook_info = check_response.json()

            if webhook_info.get('ok'):
                info = webhook_info.get('result', {})
                logger.info(f"📊 Webhook Info:")
                logger.info(f"   URL: {info.get('url')}")
                logger.info(f"   Has Custom Certificate: {info.get('has_custom_certificate')}")
                logger.info(f"   Pending Update Count: {info.get('pending_update_count')}")
                logger.info(f"   Last Error Code: {info.get('last_error_code', 'None')}")
                logger.info(f"   Last Error Message: {info.get('last_error_message', 'None')}")

                return True
        else:
            logger.error(f"❌ Ошибка при установке webhook: {result.get('description')}")
            return False

    except Exception as e:
        logger.error(f"💥 Ошибка: {e}")
        return False

def remove_webhook():
    """Remove webhook"""
    try:
        logger.info("🔌 Удаляю webhook...")
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        response = requests.post(url, data={"url": ""}, timeout=10)
        result = response.json()

        if result.get('ok'):
            logger.info("✅ Webhook удален")
            return True
        else:
            logger.error(f"❌ Ошибка: {result.get('description')}")
            return False
    except Exception as e:
        logger.error(f"💥 Ошибка: {e}")
        return False

if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'remove':
        remove_webhook()
    else:
        setup_webhook()
