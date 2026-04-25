import openai
import pdfplumber
import io
from config import OPENAI_API_KEY, OPENAI_MODEL
from policy_loader import build_system_prompt

openai.api_key = OPENAI_API_KEY


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Извлекает текст из PDF."""
    text_parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return "\n\n".join(text_parts)


async def analyze_article(pdf_bytes: bytes, mode: str = "classical", lang: str = "ru") -> str:
    """
    Анализирует статью и возвращает результат.
    mode: "classical" или "rm"
    """
    article_text = extract_text_from_pdf(pdf_bytes)

    if not article_text.strip():
        return "Не удалось извлечь текст из PDF. Возможно файл содержит только изображения."

    if len(article_text) > 40000:
        article_text = article_text[:40000] + "\n\n[...текст обрезан — анализируй то что есть...]"

    system_prompt = build_system_prompt(mode, lang)

    user_message = f"""Проанализируй следующую научную статью согласно инструкциям системного промпта. \
ВАЖНО: всегда выполняй анализ независимо от длины текста — анализируй то что предоставлено, не отказывайся.

--- НАЧАЛО СТАТЬИ ---
{article_text}
--- КОНЕЦ СТАТЬИ ---
"""

    client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        temperature=0.2,
        max_tokens=8000
    )

    return response.choices[0].message.content


async def adjust_analysis(previous_result: str, instruction: str, lang: str = "ru") -> str:
    """Усиливает или ослабляет выводы предыдущего анализа."""

    lang_note = (
        "Отвечай ТОЛЬКО на русском языке."
        if lang == "ru" else
        "Respond ONLY in English."
    )

    client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": f"You are a scientific reasoning analyst. {lang_note}"},
            {"role": "assistant", "content": previous_result},
            {"role": "user", "content": instruction}
        ],
        temperature=0.3,
        max_tokens=3000
    )

    return response.choices[0].message.content


async def ask_about_analysis(previous_result: str, question: str, lang: str = "en") -> str:
    """Отвечает на вопрос пользователя по результату анализа.
    Автоматически отвечает на языке вопроса пользователя."""

    system = (
        "You are a scientific reasoning analyst. "
        "IMPORTANT: Detect the language of the user's question and respond in THAT SAME language. "
        "If the user writes in Chinese — respond in Chinese. "
        "If in Ukrainian — respond in Ukrainian. "
        "If in Spanish — respond in Spanish. And so on. "
        "The user has already received an analysis report and is asking a follow-up question about it. "
        "Answer concisely and clearly, referring to specific findings from the report where relevant. "
        "Do not repeat the entire report — only answer what is asked."
    )

    client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "assistant", "content": previous_result},
            {"role": "user", "content": question}
        ],
        temperature=0.3,
        max_tokens=1500
    )

    return response.choices[0].message.content
