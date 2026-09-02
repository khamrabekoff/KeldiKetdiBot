import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
WEBHOOK_DOMAIN = os.getenv('WEBHOOK_DOMAIN', 'localhost')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', f'https://{WEBHOOK_DOMAIN}/webhook')
ADMIN_SECRET = os.getenv('ADMIN_SECRET', 'change_me_immediately')
DATABASE_PATH = os.getenv('DATABASE_PATH', 'keldi_ketdi.db')
FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
CRON_SECRET = os.getenv('CRON_SECRET', 'change_me_cron_secret')
DEPLOY_SECRET = os.getenv('DEPLOY_SECRET', 'change_me_deploy_secret')

BOT_VERSION = "5.0 (Webhook Edition)"

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not set in .env file!")
if ADMIN_SECRET == 'change_me_immediately':
    raise ValueError("❌ ADMIN_SECRET is default! Set it in .env file!")
