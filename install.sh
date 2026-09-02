#!/bin/bash
# Automatic installation script for Keldi-Ketdi Bot v5.1 on PythonAnywhere

set -e  # Exit on error

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  🤖 KELDI-KETDI BOT v5.1 - AUTOMATIC INSTALLATION          ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get username from current path or ask
if [ -z "$USERNAME" ]; then
    USERNAME=$(whoami)
fi

echo -e "${BLUE}📝 Текущий пользователь: $USERNAME${NC}"
echo ""

# Step 1: Activate virtual environment
echo -e "${BLUE}1️⃣ Активирую виртуальное окружение...${NC}"
source /home/$USERNAME/.virtualenvs/bot_v2_env/bin/activate 2>/dev/null || {
    echo -e "${YELLOW}⚠️  Виртуальное окружение не найдено, создаю...${NC}"
    mkvirtualenv --python=/usr/bin/python3.9 bot_v2_env
    source /home/$USERNAME/.virtualenvs/bot_v2_env/bin/activate
}
echo -e "${GREEN}✅ Виртуальное окружение активировано${NC}"
echo ""

# Step 2: Install dependencies
echo -e "${BLUE}2️⃣ Устанавливаю зависимости...${NC}"
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt > /dev/null 2>&1
echo -e "${GREEN}✅ Зависимости установлены${NC}"
echo ""

# Step 3: Check .env file
echo -e "${BLUE}3️⃣ Проверяю конфиг .env...${NC}"
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠️  .env файл не найден, создаю из примера...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}⚠️  Отредактируй .env файл вручную! Нужно заполнить:${NC}"
    echo "   - WEBHOOK_DOMAIN (твой username на PythonAnywhere)"
    echo "   - WEBHOOK_URL (https://username.pythonanywhere.com/webhook)"
    echo "   - DATABASE_PATH (/home/username/keldi_ketdi.db)"
else
    # Check if WEBHOOK_DOMAIN is configured
    if grep -q "your-username" ".env"; then
        echo -e "${YELLOW}⚠️  WEBHOOK_DOMAIN ещё не настроен!${NC}"
        echo "   Отредактируй .env файл и замени 'your-username' на твой реальный username"
        echo ""
        echo "   Текущее значение:"
        grep "WEBHOOK_DOMAIN" .env
        echo ""
        read -p "Продолжить? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
fi
echo -e "${GREEN}✅ .env файл проверен${NC}"
echo ""

# Step 4: Initialize database
echo -e "${BLUE}4️⃣ Инициализирую базу данных...${NC}"
python -c "import database; database.init_db()" 2>/dev/null || true
echo -e "${GREEN}✅ БД инициализирована${NC}"
echo ""

# Step 5: Check if database exists
if [ -f "keldi_ketdi.db" ]; then
    SIZE=$(du -h keldi_ketdi.db | cut -f1)
    echo -e "${GREEN}✅ БД файл существует ($SIZE)${NC}"
else
    echo -e "${YELLOW}⚠️  БД файл не найден (будет создана при первом запуске)${NC}"
fi
echo ""

# Step 6: Verify installation
echo -e "${BLUE}5️⃣ Проверяю установку...${NC}"
python -c "
import config
import database as db
import analytics
import audit
import excel_export
import pdf_export
print('✅ Все модули загружены успешно')
print(f'✅ Bot Version: {config.BOT_VERSION}')
" && echo -e "${GREEN}✅ Все модули работают${NC}" || echo -e "${YELLOW}⚠️  Проблема с модулями${NC}"
echo ""

# Step 7: Final message
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗"
echo -e "║  ✅ УСТАНОВКА ЗАВЕРШЕНА!                                      ║"
echo -e "╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}📋 СЛЕДУЮЩИЕ ШАГИ:${NC}"
echo ""
echo "1️⃣  Отредактируй .env файл (если нужно):"
echo "    nano .env"
echo ""
echo "2️⃣  Проверь что Web App запущено на PythonAnywhere:"
echo "    Web → Reload (зелёная кнопка)"
echo ""
echo "3️⃣  Установи webhook в Telegram:"
echo "    python -c \"from set_webhook import setup_webhook; setup_webhook()\""
echo ""
echo "4️⃣  Тесни бота:"
echo "    Отправь боту: /admin admin2026"
echo ""
echo -e "${YELLOW}📝 ВАЖНО: Если .env был только что создан, отредактируй его перед началом!${NC}"
echo ""
echo -e "${GREEN}🎉 Бот готов к работе!${NC}"
echo ""
