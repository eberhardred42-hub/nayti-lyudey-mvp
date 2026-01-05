from fastapi import FastAPI
from pydantic import BaseModel
import uuid
import re
from datetime import datetime

app = FastAPI()
SESSIONS = {}

class SessionCreate(BaseModel):
    profession_query: str


class ChatMessage(BaseModel):
    session_id: str
    type: str
    text: str | None = None


def make_empty_vacancy_kb():
    """Create an empty vacancy knowledge base."""
    return {
        "role": {
            "role_title": None,
            "role_domain": None,
            "role_seniority": None,
        },
        "company": {
            "company_location_city": None,
            "company_location_region": None,
            "work_format": None,  # office/hybrid/remote/unknown
        },
        "compensation": {
            "salary_min_rub": None,
            "salary_max_rub": None,
            "salary_comment": None,
        },
        "employment": {
            "employment_type": None,  # full-time/part-time/project/unknown
            "schedule_comment": None,
        },
        "requirements": {
            "experience_years_min": None,
            "education_level": None,  # courses/higher/specialized/unknown
            "hard_skills": [],
            "soft_skills": [],
        },
        "responsibilities": {
            "tasks": [],
            "raw_vacancy_text": None,
        },
        "sourcing": {
            "suggested_channels": [],
        },
        "meta": {
            "filled_fields_count": 0,
            "missing_fields": [],
            "last_updated_iso": None,
        },
    }


def count_filled_fields(kb):
    """Count filled scalar and list fields in vacancy KB."""
    count = 0
    for section in kb:
        if section == "meta":
            continue
        for field, value in kb[section].items():
            if isinstance(value, list):
                count += len(value)
            elif value is not None and value != "":
                count += 1
    return count


def compute_missing_fields(kb):
    """Compute required missing fields for MVP."""
    missing = []
    
    # Must-have 1: role title OR tasks not empty
    has_role_title = kb["role"]["role_title"] is not None
    has_tasks = len(kb["responsibilities"]["tasks"]) > 0
    if not (has_role_title or has_tasks):
        missing.append("role.role_title OR responsibilities.tasks")
    
    # Must-have 2: work format
    if kb["company"]["work_format"] is None:
        missing.append("company.work_format")
    
    # Must-have 3: location (city OR region)
    has_city = kb["company"]["company_location_city"] is not None
    has_region = kb["company"]["company_location_region"] is not None
    if not (has_city or has_region):
        missing.append("company.company_location_city OR company_location_region")
    
    # Must-have 4: employment type
    if kb["employment"]["employment_type"] is None:
        missing.append("employment.employment_type")
    
    # Must-have 5: compensation (at least one of three)
    has_salary = (
        kb["compensation"]["salary_min_rub"] is not None
        or kb["compensation"]["salary_max_rub"] is not None
        or kb["compensation"]["salary_comment"] is not None
    )
    if not has_salary:
        missing.append("compensation (min/max/comment)")
    
    return missing


def update_meta(kb):
    """Update meta fields: filled_fields_count, missing_fields, last_updated_iso."""
    kb["meta"]["filled_fields_count"] = count_filled_fields(kb)
    kb["meta"]["missing_fields"] = compute_missing_fields(kb)
    kb["meta"]["last_updated_iso"] = datetime.utcnow().isoformat() + "Z"


def parse_work_format(text):
    """Simple heuristic for work_format from text."""
    low = text.lower()
    if "удал" in low or "remote" in low:
        return "remote"
    elif "гибрид" in low:
        return "hybrid"
    elif "офис" in low or "office" in low:
        return "office"
    return None


def parse_employment_type(text):
    """Simple heuristic for employment_type from text."""
    low = text.lower()
    if "фулл" in low or "full" in low:
        return "full-time"
    elif "парт" in low or "part" in low:
        return "part-time"
    elif "проект" in low or "project" in low:
        return "project"
    return None


def parse_salary(text):
    """Parse salary from text, return (min, max, comment)."""
    low = text.lower()
    
    # Find all numbers, including check for 'к' suffix
    # Handle patterns: 200к, 200 000, 200-300к, etc.
    pattern = r'(\d+(?:\s\d+)*)\s*[кК]?'
    
    numbers = []
    found_k = False
    
    # Simple approach: split by common delimiters and find numbers
    import re
    # Look for number patterns with possible 'к' suffix
    parts = re.split(r'[-\s,;|]', low)
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Check if ends with 'к'
        has_k = part.endswith('к') or part.endswith('k')
        
        # Extract just digits
        digits = ''.join(c for c in part if c.isdigit())
        if digits:
            try:
                num = int(digits)
                if has_k:
                    num *= 1000
                    found_k = True
                numbers.append(num)
            except:
                pass
    
    if not numbers:
        return None, None, None
    
    # If we found 'к' and have small numbers without it, multiply them too
    if found_k and any(n < 1000 for n in numbers):
        numbers = [n * 1000 if n < 1000 else n for n in numbers]
    
    # Remove duplicates and sort
    numbers = sorted(set(numbers))
    
    if len(numbers) == 1:
        return None, None, f"около {numbers[0]:,} руб"
    elif len(numbers) >= 2:
        return numbers[0], numbers[-1], None
    
    return None, None, None


def parse_location(text):
    """Parse location from text, return (city, region)."""
    low = text.lower()
    
    # Simple dictionary of major Russian cities
    cities = {
        "москва": "москва",
        "спб": "санкт-петербург",
        "санкт-петербург": "санкт-петербург",
        "питер": "санкт-петербург",
        "екатеринбург": "екатеринбург",
        "казань": "казань",
        "новосибирск": "новосибирск",
    }
    
    for city_key, city_name in cities.items():
        if city_key in low:
            return city_name, None
    
    # If no city found, try to extract as region
    return None, text if len(text) < 100 else None


def ensure_session(sid: str, profession_query: str | None = None):
    if sid not in SESSIONS:
        SESSIONS[sid] = {
            "profession_query": profession_query or "",
            "state": "awaiting_flow",
            "vacancy_text": None,
            "tasks": None,
            "clarifications": [],
            "vacancy_kb": make_empty_vacancy_kb(),
        }
    return SESSIONS[sid]


@app.post("/chat/message")
def chat_message(body: ChatMessage):
    sid = body.session_id
    msg_type = body.type
    text = (body.text or "").strip()

    # Ensure session exists
    session = ensure_session(sid)

    # default response
    reply = ""
    quick_replies = []
    should_show_free_result = False

    state = session.get("state")

    if msg_type == "start":
        session["state"] = "awaiting_flow"
        reply = "Привет 🙂 Супер, что ты решил подойти к найму спокойно. Есть текст вакансии или только описание задач?"
        quick_replies = ["Есть текст вакансии", "Нет вакансии, есть задачи"]
        should_show_free_result = False
        return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": should_show_free_result}

    # user messages
    if state == "awaiting_flow":
        low = text.lower()
        if "есть" in low and "ваканс" in low:
            session["state"] = "awaiting_vacancy_text"
            reply = "Понял — вставь, пожалуйста, текст вакансии целиком."
        elif "нет" in low and ("ваканс" in low or "опис" in low):
            session["state"] = "awaiting_tasks"
            reply = "Хорошо — опиши, пожалуйста, 5–10 задач тезисно."
        else:
            reply = "Не совсем понял. Есть текст вакансии или только задачи?"
            quick_replies = ["Есть текст вакансии", "Нет вакансии, есть задачи"]
        return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": False}

    if state == "awaiting_vacancy_text":
        # accept long text
        if len(text) > 200:
            session["vacancy_text"] = text
            session["state"] = "awaiting_clarifications"
            
            # Update KB: raw text and extract tasks
            kb = session["vacancy_kb"]
            kb["responsibilities"]["raw_vacancy_text"] = text
            
            # Simple task extraction: split by newlines, filter empty
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            if lines:
                # Try to find bullet points or numbered items
                tasks = []
                for line in lines:
                    # Remove common prefixes: -, •, number)
                    clean = re.sub(r'^[\-•]\s*', '', line)
                    clean = re.sub(r'^\d+[\.\)]\s*', '', clean)
                    if clean and len(clean) > 5:
                        tasks.append(clean)
                
                if tasks:
                    kb["responsibilities"]["tasks"] = tasks[:10]  # limit to 10
                else:
                    kb["responsibilities"]["tasks"] = ["См. текст вакансии выше"]
            else:
                kb["responsibilities"]["tasks"] = ["См. текст вакансии выше"]
            
            update_meta(kb)
            
            reply = "Спасибо — пара уточнений: 1) город и формат, 2) бюджет, 3) занятость. Ответь одним сообщением."
        else:
            reply = "Пожалуйста, вставь текст вакансии целиком (подробнее, >200 символов)."
        return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": False}

    if state == "awaiting_tasks":
        session["tasks"] = text
        session["state"] = "awaiting_clarifications"
        
        # Update KB: parse tasks
        kb = session["vacancy_kb"]
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if lines:
            tasks = []
            for line in lines:
                # Remove common prefixes
                clean = re.sub(r'^[\-•]\s*', '', line)
                clean = re.sub(r'^\d+[\.\)]\s*', '', clean)
                if clean and len(clean) > 3:
                    tasks.append(clean)
            if tasks:
                kb["responsibilities"]["tasks"] = tasks[:10]
        
        update_meta(kb)
        
        reply = "Спасибо — пару уточнений: 1) город и формат, 2) бюджет, 3) занятость. Ответь одним сообщением."
        return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": False}

    if state == "awaiting_clarifications":
        session.setdefault("clarifications", []).append(text)
        session["state"] = "free_ready"
        
        # Update KB: parse clarifications (город/формат, бюджет, занятость)
        kb = session["vacancy_kb"]
        
        # Try to parse work_format
        fmt = parse_work_format(text)
        if fmt:
            kb["company"]["work_format"] = fmt
        
        # Try to parse employment_type
        emp = parse_employment_type(text)
        if emp:
            kb["employment"]["employment_type"] = emp
        
        # Try to parse salary
        sal_min, sal_max, sal_comment = parse_salary(text)
        if sal_min is not None:
            kb["compensation"]["salary_min_rub"] = sal_min
        if sal_max is not None:
            kb["compensation"]["salary_max_rub"] = sal_max
        if sal_comment is not None:
            kb["compensation"]["salary_comment"] = sal_comment
        
        # Try to parse location
        city, region = parse_location(text)
        if city:
            kb["company"]["company_location_city"] = city
        if region:
            kb["company"]["company_location_region"] = region
        
        update_meta(kb)
        
        reply = "Готово! Я собрал бесплатный результат ниже 🙂"
        should_show_free_result = True
        return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": should_show_free_result}

    # fallback
    reply = "Хорошо, записал."
    return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": False}

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/vacancy")
def get_vacancy(session_id: str):
    """Get vacancy knowledge base for a session."""
    session = ensure_session(session_id)
    kb = session.get("vacancy_kb", make_empty_vacancy_kb())
    
    return {
        "session_id": session_id,
        "vacancy_kb": kb,
        "missing_fields": kb["meta"]["missing_fields"],
        "filled_fields_count": kb["meta"]["filled_fields_count"],
    }


@app.get("/report/free")
def get_free_report(session_id: str):
    """Generate and return a free report from the vacancy KB."""
    session = ensure_session(session_id)
    kb = session.get("vacancy_kb", make_empty_vacancy_kb())
    profession_query = session.get("profession_query", "")
    
    # Generate free report
    free_report = generate_free_report(kb, profession_query)
    
    # Optionally cache in session (but not required)
    session["free_report"] = free_report
    session["free_report_generated_at"] = datetime.utcnow().isoformat() + "Z"
    
    return {
        "session_id": session_id,
        "free_report": free_report,
        "generated_at_iso": session["free_report_generated_at"],
        "kb_meta": {
            "missing_fields": kb["meta"]["missing_fields"],
            "filled_fields_count": kb["meta"]["filled_fields_count"],
        },
    }

def generate_free_report(kb, profession_query=""):
    """Generate a free report from vacancy KB using simple heuristics."""
    
    # Extract useful data from KB
    role_title = kb["role"]["role_title"]
    role_domain = kb["role"]["role_domain"]
    tasks = kb["responsibilities"]["tasks"]
    work_format = kb["company"]["work_format"]
    city = kb["company"]["company_location_city"]
    employment_type = kb["employment"]["employment_type"]
    salary_min = kb["compensation"]["salary_min_rub"]
    salary_max = kb["compensation"]["salary_max_rub"]
    salary_comment = kb["compensation"]["salary_comment"]
    raw_text = kb["responsibilities"]["raw_vacancy_text"] or ""
    
    low_text = raw_text.lower()
    low_query = profession_query.lower()
    
    # 1. Headline
    headline_parts = ["Держи бесплатный результат поиска"]
    if role_title:
        headline_parts.append(f"по {role_title.lower()}")
    elif role_domain:
        headline_parts.append(f"в сфере {role_domain}")
    headline = " ".join(headline_parts) + " 🎯"
    
    # 2. Where to search
    where_to_search = []
    
    # Always include HH
    where_to_search.append({
        "title": "Основные площадки",
        "bullets": [
            "HeadHunter (HH) — основной источник резюме",
            "LinkedIn — проверь профили и Recruiter функции",
        ]
    })
    
    # Add location-specific channels if office/hybrid and city known
    if work_format in ["office", "hybrid"] and city:
        where_to_search.append({
            "title": f"Локальные каналы ({city.title()})",
            "bullets": [
                f"Telegram-чаты по IT/бизнесу в {city.title()}",
                "VK сообщества профессионалов",
                "Авито (для линейных/офисных позиций)",
            ]
        })
    
    # Add domain-specific channels
    is_it = "it" in low_query or any(w in low_text for w in ["python", "java", "golang", "программ", "разработ", "backend", "frontend"])
    is_creative = any(w in low_text for w in ["дизайн", "маркетинг", "реклам", "контент", "креатив"])
    is_sales = any(w in low_text for w in ["продажа", "sales", "менеджер", "бизнес-развитие"])
    
    if is_it:
        where_to_search.append({
            "title": "IT-специфичные каналы",
            "bullets": [
                "Habr Career",
                "Telegram IT-чаты по стеку (Python, Go, JS и т.д.)",
                "GitHub (прямой поиск по профилям)",
            ]
        })
    
    if is_creative:
        where_to_search.append({
            "title": "Креативные каналы",
            "bullets": [
                "Behance, Dribbble (портфолио дизайнеров)",
                "Telegram-каналы творческих сообществ",
                "TikTok/YouTube (для контент-мейкеров)",
            ]
        })
    
    if is_sales:
        where_to_search.append({
            "title": "Продажи и управление",
            "bullets": [
                "LinkedIn (сетевой поиск)",
                "Telegram-каналы бизнес-сообществ",
                "Рекомендации и рефералы внутри сети",
            ]
        })
    
    # If no specific domain, add general recommendations
    if not (is_it or is_creative or is_sales) and len(where_to_search) == 1:
        where_to_search.append({
            "title": "Альтернативные каналы",
            "bullets": [
                "Telegram-сообщества профессионалов",
                "VK группы (зачастую живые обсуждения)",
                "Рефералы и личные контакты",
            ]
        })
    
    # 3. What to screen
    what_to_screen = [
        "Резюме/портфолио: актуальность, ясность стека и опыта",
        "Примеры работ/кейсы: релевантность к твоим задачам",
        "Мягкие навыки: общительность, ответственность, проактивность",
    ]
    
    if tasks:
        what_to_screen.append("Понимание твоих задач: может ли кандидат их объяснить своими словами")
    
    if is_it:
        what_to_screen.append("Знание инструментов: какие стеки/фреймворки точно нужны")
        what_to_screen.append("Pet проекты: показывают интерес к профессии")
    
    if is_creative:
        what_to_screen.append("Чувство стиля: соответствует ли эстетика твоему видению")
        what_to_screen.append("Процесс работы: может объяснить решения и ограничения")
    
    if is_sales:
        what_to_screen.append("Track record: цифры, результаты, достижения")
        what_to_screen.append("Энергия и амбициозность: готовность к росту")
    
    what_to_screen.append("Honesty red flags: недовольство предыдущими работодателями, зарплатные скачки без причины")
    what_to_screen.append("Этика найма: убедись, что нет конфликта интересов или действующего контракта")
    
    # 4. Budget reality check
    budget_status = "unknown"
    budget_bullets = []
    
    if salary_min or salary_max or salary_comment:
        budget_bullets = [
            "Если бюджет выше—сконцентрируйся на опыте и уровне сеньёра.",
            "Если бюджет ниже—рассмотри джуна с хорошим потенциалом, part-time или проектную работу.",
            "Опцион: наставничество (junior + ментор) может быть экономичнее середины.",
        ]
        if salary_comment:
            budget_bullets.insert(0, f"Твой бюджет: {salary_comment}")
        elif salary_min and salary_max:
            budget_bullets.insert(0, f"Бюджет: {salary_min:,}–{salary_max:,} ₽")
    else:
        budget_bullets = [
            "Не указан бюджет, но помни: рынок очень вариативен.",
            "Перед размещением вакансии — проверь аналогичные позиции на HH.",
            "Не боись предложить тестовое задание, чтобы оценить реального кандидата.",
        ]
    
    # 5. Next steps
    next_steps = [
        "Формирование вакансии: ясные требования, стек, условия, процесс интервью.",
        "Выбор каналов: начни с 2–3 основных (HH + специализированный).",
        "Быстрый скрининг резюме: ответь на вопрос 'может ли он/она это делать?' за 2 мин.",
    ]
    
    if work_format == "office" or work_format == "hybrid":
        next_steps.append("Организаторский момент: убедись, что есть место для работника и оборудование.")
    
    next_steps.append("Первое интервью: рассказывай о задачах, спрашивай о опыте, проверяй культуру.")
    next_steps.append("Тестовое задание (если уместно): small scope, 2–4 часа работы, реальная задача.")
    
    return {
        "headline": headline,
        "where_to_search": where_to_search,
        "what_to_screen": what_to_screen,
        "budget_reality_check": {
            "status": budget_status,
            "bullets": budget_bullets,
        },
        "next_steps": next_steps,
    }


@app.post("/sessions")
def create_session(body: SessionCreate):
    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = {
        "profession_query": body.profession_query,
        "state": "awaiting_flow",
        "vacancy_text": None,
        "tasks": None,
        "clarifications": [],
        "vacancy_kb": make_empty_vacancy_kb(),
    }
    return {"session_id": session_id}
