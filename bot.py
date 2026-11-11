"""Telegram-киногид с каталогом в Neon PostgreSQL и рекомендациями Google GenAI (Production-ready)."""

import asyncio
import html
import json
import logging
import os

import asyncpg
from google import genai
from google.genai import types
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message
from dotenv import load_dotenv


load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

if not all((BOT_TOKEN, GEMINI_API_KEY, DATABASE_URL)):
    raise RuntimeError(
        "Задайте BOT_TOKEN, GEMINI_API_KEY и DATABASE_URL в переменных окружения."
    )

# Инициализация нового клиента Google GenAI
client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_INSTRUCTION = """Ты — умный киногид. Подбирай варианты ИСКЛЮЧИТЕЛЬНО из переданного каталога.
Объясни, почему тайтл подходит, и дай краткое интригующее описание без спойлеров.
Не придумывай названия, факты или ссылки. Если точного совпадения нет, укажи это в поле note,
но предложи ближайшую альтернативу из каталога. Верни от 1 до 3 рекомендаций.

Верни СТРОГО валидный JSON в следующем формате (без блоков markdown вроде ```json):
{
  "note": "короткий текст или пустая строка",
  "recommendations": [
    {
      "title": "точное название из каталога",
      "reason": "почему подходит",
      "description": "описание без спойлеров"
    }
  ]
}"""

# Основная рабочая модель
PRIMARY_MODEL = "gemini-3.8-flash"

pool: asyncpg.Pool | None = None
router = Router()
dispatcher = Dispatcher()
dispatcher.include_router(router)

SEED_CATALOG = [
    {
        "item_type": "film",
        "title": "Одиссея",
        "original_title": "The Odyssey",
        "year": 2026,
        "genres": "Боевик, Приключения, Фэнтези, Драма",
        "plot_short": "Монументальная экранизация древнегреческого эпоса о десятилетнем странствии царя Итаки домой после падения Трои.",
        "plot_full": "После разрушительной осады Трои царь Итаки Одиссей отправляется в обратный путь через Средиземное море во главе уцелевшего войска. Разгневав Посейдона, герои сбиваются с курса и сталкиваются с мифическими испытаниями: циклопом Полифемом, чарами Цирцеи, сиренами и Сциллой с Харибдой. На Итаке Пенелопа противостоит женихам, а Телемах пытается отстоять наследие отца.",
        "link": "[https://kinobase.org/film/326502-odisseya](https://kinobase.org/film/326502-odisseya)",
        "recommendation_tags": "Темы: долгий путь домой, античная мифология, верность и предательство, рок, испытание воли, гнев богов. Настроение: эпическое, мрачное, масштабное, драматическое. Похожие: Гладиатор, Троя, Интерстеллар, Северянин.",
    },
    {
        "item_type": "film",
        "title": "Сердце зверя",
        "original_title": "Heart of the Beast",
        "year": 2026,
        "genres": "Боевик, Драма, Приключения, Триллер",
        "plot_short": "Экс-спецназовец и его боевой пес ведут отчаянную борьбу за жизнь посреди суровой дикой природы Аляски после авиакатастрофы.",
        "plot_full": "Отставной офицер Джеймс Белмонт пытается справиться с прошлым и живет уединенно вместе с верной армейской овчаркой Одином. После авиакатастрофы они оказываются в глуши Аляски без связи и снаряжения. Им предстоит преодолеть ледяную пустыню, опасности дикой природы и преследование наемников.",
        "link": "[https://kinobase.org/film/326660-serdtse-zverya](https://kinobase.org/film/326660-serdtse-zverya)",
        "recommendation_tags": "Темы: выживание в дикой природе, верность животных, ПТСР, преодоление травмы. Настроение: напряженное, адреналиновое, жизнеутверждающее, суровое. Похожие: Схватка, Выживший, Зов предков.",
    },
    {
        "item_type": "film",
        "title": "Джимми",
        "original_title": "Jimmy",
        "year": 2026,
        "genres": "Биография, Драма, Военный, История",
        "plot_short": "Биографическая драма о голливудской легенде Джимми Стюарте, который на вершине славы добровольно ушел на фронты Второй мировой войны.",
        "plot_full": "Джеймс «Джимми» Стюарт находится в зените голливудской славы, но сомневается в подлинности своего призвания. Когда США вступают во Вторую мировую войну, он добивается призыва в армейскую авиацию, отказывается от безопасной службы в тылу и становится командиром эскадрильи бомбардировщиков. Боевые вылеты навсегда меняют его.",
        "link": "[https://kinobase.org/film/327110-dzhimmi](https://kinobase.org/film/327110-dzhimmi)",
        "recommendation_tags": "Темы: золотой век Голливуда, военный долг, моральный выбор, цена славы, героизм без прикрас. Настроение: вдохновляющее, рефлексивное, патриотическое, глубокое. Похожие: Авиатор, По соображениям совести, Оппенгеймер, Властелины воздуха.",
    },
    {
        "item_type": "film",
        "title": "Любой ценой",
        "original_title": "By Any Means",
        "year": 2026,
        "genres": "Боевик, Криминал, Триллер, Драма",
        "plot_short": "Исторический триллер о тайном союзе темнокожего агента ФБР и безжалостного мафиозного киллера ради расследования расправ ку-клукс-клановцев.",
        "plot_full": "В 1966 году в Миссисипи серия убийств активистов остается без расследования: местные власти связаны с Ку-клукс-кланом, а свидетели запуганы. ФБР объединяет идеалистичного темнокожего агента Уэйна Страйдера и мафиозного киллера Грегори Скарпу. Необычный дуэт пытается раскрыть заговор и добиться правды.",
        "link": "[https://kinobase.org/film/246037-lyuboy-tsenoy](https://kinobase.org/film/246037-lyuboy-tsenoy)",
        "recommendation_tags": "Темы: расовое неравенство, напарники-антиподы, мафия и Ку-клукс-клан, правосудие вне закона. Настроение: мрачное, жесткое, бескомпромиссное, исторически напряженное. Похожие: Миссисипи в огне, Черный клановец, Донни Браско.",
    },
    {
        "item_type": "film",
        "title": "Вышка 2",
        "original_title": "Fall 2: Deadpoint",
        "year": 2026,
        "genres": "Драма, Триллер, Приключения",
        "plot_short": "Сиквел survival-хита: сестра погибшей экстремалки бросает вызов смертоносному скальному маршруту в Таиланде.",
        "plot_full": "После гибели сестры Шайло Джакс пытается справиться с горем и находит ее блокнот экстремальных маршрутов. Она решает завершить начатое восхождение на гору Кван в Таиланде. Камнепад срезает страховку, и группа оказывается на крошечном карнизе над пропастью без надежды на скорую помощь.",
        "link": "[https://kinobase.org/film/326366-vyshka-2](https://kinobase.org/film/326366-vyshka-2)",
        "recommendation_tags": "Темы: акрофобия, экстремальный спорт, горечь утраты, выживание на грани. Настроение: головокружительное, тревожное, клаустрофобное, паническое. Похожие: Вышка, 127 часов, Вертикальный предел, Дрейф.",
    },
    {
        "item_type": "serial",
        "title": "Спецназ: Новобранцы",
        "original_title": "S.W.A.T. Exiles",
        "year": 2026,
        "genres": "Боевик, Драма, Криминал",
        "plot_short": "Ветеран SWAT берет под крыло отряд проблемных кадетов и изгоев, чтобы сделать из них элитный антикризисный взвод.",
        "plot_full": "На фоне роста уличного насилия создают пилотное подразделение «Изгои», куда направляют курсантов с взысканиями и отвергнутых академией тактических специалистов. Опытный командир-ветеран должен превратить их в сплоченную команду, способную работать в опасных городских операциях, и научить доверять друг другу.",
        "link": "[https://kinobase.org/serial/326452-spetsnaz-novobrantsy](https://kinobase.org/serial/326452-spetsnaz-novobrantsy)",
        "recommendation_tags": "Темы: полицейский спецназ, второй шанс, командная сплоченность, наставничество, городские спецоперации. Настроение: динамичное, драйвовое, боевое, командное. Похожие: Спецназ города ангелов, Новобранец, Морские котики.",
    },
    {
        "item_type": "serial",
        "title": "Король Талсы",
        "original_title": "Tulsa King",
        "year": 2022,
        "genres": "Драма, Комедия, Криминал",
        "plot_short": "Отсидевший 25 лет мафиози старой закалки отправляется в провинциальную Оклахому и строит криминальную империю с нуля.",
        "plot_full": "Капо нью-йоркской мафии Дуайт Манфреди выходит на свободу после четверти века за решеткой, но вместо благодарности его отправляют в Талсу. Осознав, что старая семья его предала, Дуайт собирает вокруг себя местных чудаков, легальных продавцов каннабиса и байкеров и вступает в борьбу за влияние.",
        "link": "[https://kinobase.org/serial/203601-korol-talsy](https://kinobase.org/serial/203601-korol-talsy)",
        "recommendation_tags": "Темы: мафия старой школы, криминальный бизнес, чужак в новом месте, ирония, мужская честь, передел власти. Настроение: ироничное, брутальное, харизматичное, развлекательное. Похожие: Клан Сопрано, Лиллехаммер, Озарк, Йеллоустоун.",
    },
    {
        "item_type": "serial",
        "title": "Бродяга",
        "original_title": "Бродяга",
        "year": 2025,
        "genres": "Детектив, Мелодрама, Криминал",
        "plot_short": "Загадочный бездомный с аналитическим умом помогает молодой следовательнице распутать серию замаскированных убийств.",
        "plot_full": "Бездомный Борис находит утюг со следами крови и приносит его в полицию. Следователь Валерия Перова замечает, что находка может быть связана с делом погибшей девушки, которое ошибочно сочли несчастным случаем. Вместе они распутывают расследование, а Валерия постепенно узнает о скрытом прошлом Бориса.",
        "link": "[https://kinobase.org/serial/239574-brodyaga](https://kinobase.org/serial/239574-brodyaga)",
        "recommendation_tags": "Темы: расследование убийств, тайны прошлого, социальный контраст, неожиданный напарник, дедукция. Настроение: меланхоличное, интригующее, душевное, детективное. Похожие: Нюхач, Метод, Шерлок Холмс, Ищейка.",
    },
    {
        "item_type": "cartoon",
        "title": "Симпсоны",
        "original_title": "The Simpsons",
        "year": 1989,
        "genres": "Мультфильм, Комедия, Сатира",
        "plot_short": "Культовая сатирическая хроника жизни чудаковатой американской семьи рабочих и их безумного городка Спрингфилд.",
        "plot_full": "В Спрингфилде живет семейство Симпсонов: неуклюжий Гомер, терпеливая Мардж, сорванец Барт, умница Лиза и малышка Мэгги. Их повседневная жизнь превращается в череду комических происшествий, через которые сериал высмеивает политику, телевидение, поп-культуру, религию и человеческие слабости.",
        "link": "[https://kinobase.org/serial/244654-simpsony](https://kinobase.org/serial/244654-simpsony)",
        "recommendation_tags": "Темы: семейные ценности, сатира на общество потребления, абсурдный юмор, поп-культурные пародии. Настроение: саркастичное, смешное, теплое, ностальгическое. Похожие: Гриффины, Футурама, Южный Парк, Рик и Морти.",
    },
    {
        "item_type": "cartoon",
        "title": "Край чудес",
        "original_title": "Край чудес",
        "year": 2026,
        "genres": "Мультфильм, Приключения, Семейный, Фэнтези",
        "plot_short": "Юный художник находит скрытый в сибирской тайге сказочный мир и встает на защиту его диковинных обитателей.",
        "plot_full": "Увлеченный рисованием подросток Филипп во время экспедиции в Сибирь попадает в затерянный мир, где живут маленький народ иморов и магические звери. Когда туда вторгается корпорация, желающая добывать редкие ресурсы, Филипп и новые друзья используют смекалку, творчество и взаимное доверие, чтобы защитить этот край.",
        "link": "[https://kinobase.org/film/327022-kray-chudes](https://kinobase.org/film/327022-kray-chudes)",
        "recommendation_tags": "Темы: защита природы, сибирский фольклор, взросление, творчество, дружба. Настроение: сказочное, доброе, яркое, семейное. Похожие: Аватар, Эпик, Хранители снов, Тайна Сухаревой башни.",
    },
    {
        "item_type": "cartoon",
        "title": "Черепашки-ниндзя",
        "original_title": "Teenage Mutant Ninja Turtles",
        "year": 2012,
        "genres": "Мультфильм, Боевик, Приключения, Фантастика, Комедия",
        "plot_short": "Четверка братьев-мутантов выбирается из канализации на улицы Нью-Йорка, чтобы поедать пиццу и крушить клан Фут и инопланетян.",
        "plot_full": "Мастер ниндзюцу Сплинтер воспитывает в канализации четырех мутировавших черепашек как сыновей и обучает их искусству ниндзя. Когда Леонардо, Рафаэль, Донателло и Микеланджело впервые выходят на поверхность Нью-Йорка, им предстоит освоиться среди людей, защитить Эйприл О’Нил и противостоять Шреддеру и инопланетянам Крэнгам.",
        "link": "[https://kinobase.org/serial/326889-cherepashki-nindzya](https://kinobase.org/serial/326889-cherepashki-nindzya)",
        "recommendation_tags": "Темы: братство, взросление, боевые искусства, супергероика, комиксы, борьба со злом. Настроение: энергичное, юмористическое, боевое, подростковое. Похожие: Черепашки-ниндзя (2003), Человек-паук: Через вселенные, Юные титаны, Аватар: Легенда об Аанге.",
    },
]


async def init_db() -> None:
    """Инициализация пула соединений с Neon PostgreSQL и создание таблиц."""
    global pool
    try:
        pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=1,
            max_size=5,
            command_timeout=30,
        )
        async with pool.acquire() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS catalog (
                    id SERIAL PRIMARY KEY,
                    item_type VARCHAR NOT NULL,
                    title VARCHAR NOT NULL,
                    original_title VARCHAR,
                    year INT,
                    genres TEXT,
                    plot_short TEXT,
                    plot_full TEXT,
                    link TEXT,
                    recommendation_tags TEXT
                );
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username VARCHAR,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS recommendation_history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    user_query TEXT,
                    bot_response TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                """
            )
            catalog_is_empty = await connection.fetchval(
                "SELECT NOT EXISTS (SELECT 1 FROM catalog)"
            )
            if catalog_is_empty:
                await connection.executemany(
                    """
                    INSERT INTO catalog (
                        item_type, title, original_title, year, genres,
                        plot_short, plot_full, link, recommendation_tags
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9
                    )
                    """,
                    [
                        (
                            item["item_type"],
                            item["title"],
                            item["original_title"],
                            item["year"],
                            item["genres"],
                            item["plot_short"],
                            item["plot_full"],
                            item["link"],
                            item["recommendation_tags"],
                        )
                        for item in SEED_CATALOG
                    ],
                )
                logger.info("Каталог успешно заполнен: %d произведений", len(SEED_CATALOG))
    except Exception:
        logger.exception("Ошибка подключения к базе данных Neon PostgreSQL")
        if pool is not None:
            await pool.close()
            pool = None
        raise


@router.message(F.text == "/start")
async def start_handler(message: Message) -> None:
    """Обработка команды /start."""
    if pool is None or message.from_user is None:
        await message.answer("База данных пока недоступна. Попробуйте чуть позже.")
        return

    try:
        await pool.execute(
            """
            INSERT INTO users (user_id, username)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
            """,
            message.from_user.id,
            message.from_user.username,
        )
    except Exception:
        logger.exception("Не удалось сохранить пользователя в БД")

    await message.answer(
        "Привет! Я твой умный киногид 🎬\n\n"
        "Напиши мне, что именно ты хочешь посмотреть, под какое настроение, или назови похожий фильм — я подберу лучший вариант из базы!"
    )


async def get_catalog() -> list[asyncpg.Record]:
    """Выгрузка каталога из базы данных."""
    if pool is None:
        raise RuntimeError("База данных не инициализирована")
    return await pool.fetch(
        """
        SELECT title, original_title, item_type, year, genres,
               plot_short, plot_full, recommendation_tags, link
        FROM catalog
        ORDER BY id
        """
    )


def build_prompt(user_query: str, catalog: list[asyncpg.Record]) -> str:
    """Формирование промпта для генерации рекомендаций."""
    catalog_data = [dict(item) for item in catalog]
    return f"""Каталог (единственный источник названий и фактов):
{json.dumps(catalog_data, ensure_ascii=False)}

Запрос пользователя:
{user_query}
"""


def extract_json_safe(text: str) -> dict:
    """Безопасное извлечение и парсинг JSON из ответа языковой модели."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return json.loads(text)


async def generate_with_retry(prompt: str) -> str:
    """Запрос к Gemini с автоматическими повторами при временной перегрузке (503)."""
    max_retries = 3
    delay = 3

    for attempt in range(1, max_retries + 1):
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model=PRIMARY_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.6,
                        response_mime_type="application/json",
                    ),
                ),
                timeout=55,
            )
            if response and response.text:
                return response.text
        except Exception as e:
            logger.warning(f"Попытка {attempt} не удалась (модель занята/ошибка): {e}")
            if attempt < max_retries:
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise RuntimeError(f"Сервер Gemini перегружен (503). Попробуйте отправить запрос через минуту. Ошибка: {e}")


def render_recommendations(result_text: str, catalog: list[asyncpg.Record]) -> str:
    """Верификация и форматирование результатов в красивый HTML для Telegram."""
    result = extract_json_safe(result_text)
    if not isinstance(result, dict) or not isinstance(result.get("recommendations"), list):
        raise ValueError("Ответ модели не содержит секции рекомендаций")

    items_by_title = {item["title"].casefold(): item for item in catalog}
    recommendations = []
    used_titles = set()
    
    for recommendation in result["recommendations"]:
        if not isinstance(recommendation, dict):
            continue
        title = str(recommendation.get("title", "")).strip()
        item = items_by_title.get(title.casefold())
        if item is None or item["title"].casefold() in used_titles:
            continue
        used_titles.add(item["title"].casefold())
        recommendations.append((item, recommendation))
        if len(recommendations) == 3:
            break

    if not recommendations:
        raise ValueError("Модель не выбрала ни одного корректного тайтла из каталога")

    parts = []
    note = str(result.get("note", "")).strip()
    if note:
        parts.append(html.escape(note[:500]))

    type_names = {"film": "Фильм", "serial": "Сериал", "cartoon": "Мультфильм"}
    for item, recommendation in recommendations:
        title = html.escape(item["title"])
        link = html.escape(item["link"] or "", quote=True)
        kind = type_names.get(item["item_type"], "Произведение")
        year = f" · {item['year']}" if item["year"] else ""
        reason = html.escape(str(recommendation.get("reason", ""))[:700])
        description = html.escape(str(recommendation.get("description", ""))[:900])
        parts.append(
            f'<b><a href="{link}">{title}</a></b> <i>({kind}{year})</i>\n'
            f"💡 <i>{reason}</i>\n\n"
            f"📖 {description}"
        )
    return "\n\n".join(parts)


@router.message(F.text)
async def recommendation_handler(message: Message) -> None:
    """Главный обработчик текстовых запросов пользователя."""
    if message.text is None or message.text.startswith("/"):
        return
    if pool is None:
        await message.answer("База данных пока недоступна. Попробуйте чуть позже.")
        return

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
        catalog = await get_catalog()
        if not catalog:
            await message.answer("Каталог пока пуст. Загляните чуть позже.")
            return

        prompt = build_prompt(message.text, catalog)
        raw_response_text = await generate_with_retry(prompt)
        answer = render_recommendations(raw_response_text, catalog)
        
    except asyncio.TimeoutError:
        logger.warning("Тайм-аут ожидания ответа от ИИ")
        await message.answer("Сервис отвечает слишком долго. Попробуйте еще раз.")
        return
    except (ValueError, json.JSONDecodeError):
        logger.exception("Ошибка парсинга ответа от Gemini")
        await message.answer("Не удалось корректно обработать ответ ИИ. Пожалуйста, уточните ваш запрос.")
        return
    except Exception as err:
        logger.exception("Непредвиденная ошибка при формировании рекомендации")
        # Выдаем более понятную подсказку, если сервер перегружен
        if "503" in str(err) or "UNAVAILABLE" in str(err):
            await message.answer("Сервер Google сейчас временно перегружен. Пожалуйста, повторите запрос через минуту.")
        else:
            await message.answer("Сервис рекомендаций временно недоступен. Попробуйте позже.")
        return

    try:
        await pool.execute(
            """
            INSERT INTO recommendation_history (user_id, user_query, bot_response)
            VALUES ($1, $2, $3)
            """,
            message.from_user.id if message.from_user else 0,
            message.text,
            answer,
        )
    except Exception:
        logger.exception("Не удалось записать историю в БД")

    await message.answer(answer, disable_web_page_preview=True)


async def main() -> None:
    """Запуск приложения."""
    global pool
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        async_db = await init_db()
        logger.info("Бот успешно запущен и начал polling...")
        await dispatcher.start_polling(bot)
    finally:
        if pool is not None:
            await pool.close()
            pool = None
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем")