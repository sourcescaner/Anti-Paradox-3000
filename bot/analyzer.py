import openai
import pdfplumber
import io
from config import OPENAI_API_KEY, OPENAI_MODEL
from policy_loader import build_system_prompt

openai.api_key = OPENAI_API_KEY


# ─── Кастомные исключения ────────────────────────────────────────────────────

class PDFEmptyError(Exception):
    """PDF не содержит извлекаемого текста (сканированный или пустой)."""

class PDFReadError(Exception):
    """PDF повреждён или не может быть прочитан."""

class OpenAIRateLimitError(Exception):
    """Превышен лимит запросов к OpenAI."""

class OpenAITimeoutError(Exception):
    """OpenAI не ответил за отведённое время."""

class OpenAIConnectionError(Exception):
    """Нет соединения с OpenAI."""

class OpenAIError(Exception):
    """Общая ошибка OpenAI."""


# ─── Извлечение текста из PDF ────────────────────────────────────────────────

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Извлекает текст из PDF. Бросает PDFReadError или PDFEmptyError."""
    try:
        text_parts = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
        result = "\n\n".join(text_parts)
    except Exception as e:
        raise PDFReadError(str(e))

    if not result.strip():
        raise PDFEmptyError("No extractable text found")

    return result


# ─── Анализ статьи ───────────────────────────────────────────────────────────

async def analyze_article(pdf_bytes: bytes, mode: str = "classical", lang: str = "ru") -> str:
    """
    Анализирует статью и возвращает результат.
    Бросает специфические исключения вместо возврата строк с ошибками.
    """
    article_text = extract_text_from_pdf(pdf_bytes)  # может бросить PDFReadError / PDFEmptyError

    if len(article_text) > 40000:
        article_text = article_text[:40000] + "\n\n[...text truncated — analyze what is provided...]"

    system_prompt = build_system_prompt(mode, lang)

    user_message = (
        "Analyze the following scientific article according to the system prompt instructions. "
        "IMPORTANT: always perform the analysis regardless of text length — analyze what is provided, do not refuse.\n\n"
        "--- START OF ARTICLE ---\n"
        f"{article_text}\n"
        "--- END OF ARTICLE ---"
    )

    client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.2,
            max_tokens=8000,
            timeout=120,
        )
    except openai.RateLimitError:
        raise OpenAIRateLimitError()
    except openai.APITimeoutError:
        raise OpenAITimeoutError()
    except openai.APIConnectionError:
        raise OpenAIConnectionError()
    except openai.APIError as e:
        raise OpenAIError(str(e))

    return response.choices[0].message.content


# ─── Корректировка выводов ───────────────────────────────────────────────────

async def adjust_analysis(previous_result: str, instruction: str, lang: str = "ru") -> str:
    """Усиливает или ослабляет выводы предыдущего анализа."""

    lang_note = (
        "Отвечай ТОЛЬКО на русском языке." if lang == "ru" else
        "Відповідай ТІЛЬКИ українською мовою." if lang == "uk" else
        "Respond ONLY in English."
    )

    client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": f"You are a scientific reasoning analyst. {lang_note}"},
                {"role": "assistant", "content": previous_result},
                {"role": "user", "content": instruction}
            ],
            temperature=0.3,
            max_tokens=3000,
            timeout=120,
        )
    except openai.RateLimitError:
        raise OpenAIRateLimitError()
    except openai.APITimeoutError:
        raise OpenAITimeoutError()
    except openai.APIConnectionError:
        raise OpenAIConnectionError()
    except openai.APIError as e:
        raise OpenAIError(str(e))

    return response.choices[0].message.content


# ─── Вопросы по анализу ──────────────────────────────────────────────────────

async def ask_about_analysis(previous_result: str, question: str, lang: str = "en") -> str:
    """Отвечает на вопрос пользователя по результату анализа."""

    system = (
        "You are a scientific reasoning analyst. "
        "IMPORTANT: Detect the language of the user's question and respond in THAT SAME language. "
        "The user has already received an analysis report and is asking a follow-up question about it. "
        "Answer concisely and clearly, referring to specific findings from the report where relevant. "
        "Do not repeat the entire report — only answer what is asked."
    )

    client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "assistant", "content": previous_result},
                {"role": "user", "content": question}
            ],
            temperature=0.3,
            max_tokens=1500,
            timeout=60,
        )
    except openai.RateLimitError:
        raise OpenAIRateLimitError()
    except openai.APITimeoutError:
        raise OpenAITimeoutError()
    except openai.APIConnectionError:
        raise OpenAIConnectionError()
    except openai.APIError as e:
        raise OpenAIError(str(e))

    return response.choices[0].message.content
