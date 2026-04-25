"""
AI service for vacancy scoring, cover letters, and reply drafts.
Uses OpenAI GPT-4o-mini. All prompts are in Russian.
"""
import json
import logging
from openai import AsyncOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=settings.openai_api_key)

# Vacancy types that are almost always irrelevant for tech/professional candidates
GARBAGE_TITLES = [
    "менеджер по продажам", "торговый представитель", "промоутер", "курьер",
    "сетевой маркетинг", "mlm", "агент по недвижимости", "риелтор",
    "оператор колл-центра", "расклейщик", "грузчик", "кассир",
]

LEVEL_MAP = {
    "junior": ["junior", "джуниор", "младший", "начинающий", "стажёр", "intern"],
    "middle": ["middle", "мидл", "специалист", "разработчик", "инженер"],
    "senior": ["senior", "сеньор", "старший", "lead", "лид", "principal", "architect", "архитектор"],
}


def _detect_level(text: str) -> str | None:
    """Detect seniority level from vacancy title or description."""
    t = text.lower()
    for level, keywords in LEVEL_MAP.items():
        if any(k in t for k in keywords):
            return level
    return None


def _skill_overlap(user_skills: list[str], required_skills: list[str]) -> float:
    """Jaccard-like skill overlap: matched / required_count."""
    if not required_skills:
        return 0.7  # no requirements = neutral
    user_lower = {s.lower() for s in user_skills}
    matched = sum(1 for s in required_skills if s.lower() in user_lower)
    return matched / len(required_skills)


def _is_garbage(title: str) -> bool:
    t = title.lower()
    return any(g in t for g in GARBAGE_TITLES)


def _salary_fit(
    user_from: int | None,
    user_to: int | None,
    vac_from: int | None,
    vac_to: int | None,
) -> str:
    """Return human-readable salary fit note for the AI prompt."""
    if not vac_from and not vac_to:
        return "зарплата не указана"
    vac_mid = ((vac_from or 0) + (vac_to or vac_from or 0)) / 2
    user_min = user_from or 0
    user_max = user_to or float("inf")
    if vac_mid < user_min * 0.8:
        return f"зарплата ниже ожиданий (вакансия ~{int(vac_mid):,} ₽, ожидание от {user_min:,} ₽)"
    if user_max != float("inf") and vac_mid > user_max * 1.5:
        return f"зарплата выше ожиданий (возможно грейд не совпадает)"
    return f"зарплата подходит (~{int(vac_mid):,} ₽)"


SCORE_SYSTEM = """Ты — AI-помощник для поиска работы. Твоя задача — точно оценить, насколько вакансия подходит кандидату.

Возвращай ТОЛЬКО валидный JSON без markdown-обёртки:
{
  "score": int (0-100),
  "breakdown": {
    "skills": int (0-100),
    "level": int (0-100),
    "salary": int (0-100),
    "format": int (0-100),
    "title_fit": int (0-100)
  },
  "explanation": "2-3 предложения на русском: почему такой score, что совпало, что нет",
  "recommended": bool,
  "red_flags": ["список проблем если есть"]
}

Правила оценки:
- 80-100: отличное совпадение, рекомендую откликнуться
- 60-79: хорошее совпадение, стоит рассмотреть
- 40-59: частичное совпадение, на усмотрение
- < 40: плохое совпадение, скорее всего не подойдёт
- Если вакансия явно не по специальности (продажи, курьер и т.д.) — score < 20
- Если грейд не совпадает (senior ищет junior) — штраф 30+ баллов"""


async def score_vacancy(
    vacancy_title: str,
    company: str,
    description: str | None,
    skills_required: list[str],
    salary_from: int | None,
    salary_to: int | None,
    work_format: str | None,
    user_skills: list[str],
    user_salary_from: int | None,
    user_salary_to: int | None,
    user_work_formats: list[str],
    user_experience: int | None,
    target_role: str | None = None,
    rejected_companies: list[str] | None = None,
) -> dict:
    # Pre-filter: garbage titles → instant low score
    if _is_garbage(vacancy_title):
        logger.info("score_vacancy: garbage title detected '%s'", vacancy_title)
        return {
            "score": 5,
            "breakdown": {"skills": 0, "level": 0, "salary": 0, "format": 0, "title_fit": 5},
            "explanation": f"Вакансия '{vacancy_title}' не соответствует профилю — нерелевантная сфера.",
            "recommended": False,
            "red_flags": ["нерелевантная сфера деятельности"],
        }

    # Rejected company
    if rejected_companies and company.lower() in [c.lower() for c in rejected_companies]:
        return {
            "score": 0,
            "breakdown": {"skills": 0, "level": 0, "salary": 0, "format": 0, "title_fit": 0},
            "explanation": f"Компания '{company}' в списке исключений пользователя.",
            "recommended": False,
            "red_flags": ["компания в стоп-листе"],
        }

    # Compute context hints for AI
    skill_overlap = _skill_overlap(user_skills, skills_required)
    vac_level = _detect_level(vacancy_title) or _detect_level(description or "")
    user_level = (
        "junior" if (user_experience or 0) < 2
        else "senior" if (user_experience or 0) >= 5
        else "middle"
    )
    salary_note = _salary_fit(user_salary_from, user_salary_to, salary_from, salary_to)

    level_note = ""
    if vac_level and vac_level != user_level:
        level_note = f"⚠️ Грейд не совпадает: вакансия ищет {vac_level}, кандидат — {user_level}."

    prompt = f"""Вакансия: {vacancy_title}
Компания: {company}
Требуемые навыки: {', '.join(skills_required) if skills_required else 'не указаны'}
Формат: {work_format or 'не указан'}
Описание (фрагмент): {(description or '')[:600]}

Профиль кандидата:
Целевая роль: {target_role or 'не указана'}
Навыки: {', '.join(user_skills) if user_skills else 'не указаны'}
Опыт: {user_experience or '?'} лет
Форматы работы: {', '.join(user_work_formats) if user_work_formats else 'любой'}

Аналитика (предварительная):
- Совпадение навыков: {int(skill_overlap * 100)}% ({sum(1 for s in skills_required if s.lower() in {u.lower() for u in user_skills})} из {len(skills_required)} навыков)
- Зарплата: {salary_note}
- Грейд вакансии: {vac_level or 'не определён'}, грейд кандидата: {user_level}
{level_note}

Оцени итоговое соответствие и верни JSON."""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=512,
            temperature=0.2,
            messages=[
                {"role": "system", "content": SCORE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        result = json.loads(response.choices[0].message.content)
        logger.debug("score_vacancy: '%s' @ %s → %s", vacancy_title, company, result.get("score"))
        return result
    except Exception:
        logger.exception("score_vacancy: AI call failed for '%s'", vacancy_title)
        # Fallback: compute basic score from skill overlap
        fallback_score = int(skill_overlap * 70)
        return {
            "score": fallback_score,
            "breakdown": {"skills": int(skill_overlap * 100), "level": 50, "salary": 50, "format": 50, "title_fit": 50},
            "explanation": "Оценка рассчитана по совпадению навыков (AI недоступен).",
            "recommended": fallback_score >= 60,
            "red_flags": [],
        }


LETTER_SYSTEM = """Ты — AI-помощник для поиска работы. Пиши сопроводительные письма которые выглядят как написанные живым человеком, а не ботом.

Правила (строго):
- 3-4 предложения, максимум 120 слов
- Упомяни 2-3 конкретных навыка из пересечения вакансии и профиля
- Добавь 1 конкретный факт: опыт в годах, проект, достижение
- НЕ пиши "меня заинтересовала вакансия" — это шаблон
- НЕ пиши "готов(а) к сотрудничеству" — это мусор
- НЕ пиши "рассмотрите мою кандидатуру" — избито
- Начни с конкретики: чем занимался, что умеешь
- Адаптируй под компанию если известна её специфика
- Возвращай только текст письма, без заголовков"""


async def generate_cover_letter(
    vacancy_title: str,
    company: str,
    description: str | None,
    skills_required: list[str],
    user_skills: list[str],
    user_experience: int | None,
    tone: str,
    salary_from: int | None,
    salary_to: int | None,
    include_salary: bool,
    personalize: bool,
    custom_instructions: str | None,
    target_role: str | None = None,
) -> str:
    tone_guide = {
        "professional": "деловой стиль, без лишних слов",
        "friendly": "тёплый человечный тон, чуть менее формально",
        "concise": "предельно коротко, только факты",
    }.get(tone, "деловой стиль")

    # Compute matched skills for the prompt
    matched = [s for s in skills_required if s.lower() in {u.lower() for u in user_skills}]
    unmatched = [s for s in skills_required if s.lower() not in {u.lower() for u in user_skills}]

    salary_note = ""
    if include_salary and salary_from:
        salary_note = f"\nЗарплатные ожидания: от {salary_from:,} ₽"
        if salary_to:
            salary_note += f" до {salary_to:,} ₽"

    company_note = f"Компания: {company}. " if personalize else ""
    custom_note = f"\nДополнительно от кандидата: {custom_instructions}" if custom_instructions else ""

    prompt = f"""Напиши сопроводительное письмо.

{company_note}Вакансия: {vacancy_title}
Целевая роль кандидата: {target_role or vacancy_title}
Опыт кандидата: {user_experience or '?'} лет
Навыки кандидата: {', '.join(user_skills[:10]) if user_skills else 'не указаны'}

Совпадающие навыки с вакансией: {', '.join(matched[:5]) if matched else 'не определены'}
Требуются но нет: {', '.join(unmatched[:3]) if unmatched else 'нет'}
Требования вакансии: {', '.join(skills_required[:8]) if skills_required else 'не указаны'}
Описание (фрагмент): {(description or '')[:400]}
{salary_note}
Тон: {tone_guide}{custom_note}

Напиши письмо (3-4 предложения, ~80-120 слов, на русском):"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=300,
            temperature=0.7,
            messages=[
                {"role": "system", "content": LETTER_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception:
        logger.exception("generate_cover_letter: AI call failed for '%s'", vacancy_title)
        raise


REPLY_SYSTEM = """Ты — AI-помощник для поиска работы. Составь ответ кандидата работодателю.

Правила:
- 2-4 предложения, максимум 80 слов
- Отвечай по существу на вопрос работодателя
- Если работодатель спрашивает про навыки/опыт — используй КОНКРЕТНЫЕ навыки из профиля кандидата
- Если спрашивают про зарплату — отвечай на основе ожиданий кандидата
- Подтверди интерес + добавь конкретику из профиля
- Пиши как живой человек, не как бот
- НЕ пиши "буду рад" "надеюсь на сотрудничество"
- Возвращай только текст ответа"""


async def draft_reply(
    employer_message: str,
    vacancy_title: str,
    company: str,
    conversation_history: list[dict],
    tone: str,
    custom_instructions: str | None,
    user_skills: list[str] | None = None,
    user_experience: int | None = None,
    target_role: str | None = None,
    salary_from: int | None = None,
    salary_to: int | None = None,
) -> str:
    tone_guide = {
        "professional": "деловой стиль",
        "friendly": "тёплый, человечный тон",
        "concise": "минимум слов, по делу",
    }.get(tone, "деловой стиль")

    history_text = ""
    if conversation_history:
        history_text = "\nИстория переписки:\n" + "\n".join(
            f"{'Работодатель' if m['role'] == 'employer' else 'Кандидат'}: {m['content']}"
            for m in conversation_history[-6:]
        )

    custom_note = f"\nПожелания: {custom_instructions}" if custom_instructions else ""

    skills_text = ", ".join((user_skills or [])[:12]) or "не указаны"
    salary_text = ""
    if salary_from:
        salary_text = f"от {salary_from:,} ₽"
        if salary_to:
            salary_text += f" до {salary_to:,} ₽"

    prompt = f"""Профиль кандидата:
Целевая роль: {target_role or vacancy_title}
Опыт: {user_experience or '?'} лет
Навыки: {skills_text}
Зарплатные ожидания: {salary_text or 'не указаны'}

Вакансия: {vacancy_title} в {company}
Тон: {tone_guide}{custom_note}{history_text}

Новое сообщение работодателя:
{employer_message}

Напиши ответ кандидата, опираясь на его реальные навыки и опыт:"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=200,
            temperature=0.6,
            messages=[
                {"role": "system", "content": REPLY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception:
        logger.exception("draft_reply: AI call failed")
        raise
