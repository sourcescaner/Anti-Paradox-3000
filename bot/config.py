import os
from dotenv import load_dotenv

load_dotenv()  # читает .env файл автоматически

# Telegram Bot Token
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# OpenAI API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Модель OpenAI
OPENAI_MODEL = "gpt-4o"

# Лимиты
MAX_PDF_SIZE_MB = 20
MAX_FREE_ANALYSES = 3  # бесплатных анализов на пользователя

# Языки
DEFAULT_LANGUAGE = "en"

# Администраторы — безлимитный доступ
ADMIN_USER_IDS = {1010993409}  # Roman Berezuiev

# Монетизация
ANALYSES_PER_PACK = 3    # анализов в пакете
STARS_PER_PACK = 75      # ~$1 в Telegram Stars
