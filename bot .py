import logging
import asyncio
import os
import re
import json
import sys
import time
import zipfile
import asyncpg
from aiohttp import web
from groq import AsyncGroq
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
                          InlineKeyboardButton, FSInputFile, CallbackQuery)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from datetime import datetime

# --- 1. KONFIGURATSIYA VA LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]  # Render'da fayl log kerak emas
)
logger = logging.getLogger(__name__)

# Environment variable'lardan o'qish
API_TOKEN    = os.getenv('BOT_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
ADMIN_ID     = os.getenv('ADMIN_ID')
DATABASE_URL = os.getenv('DATABASE_URL')          # Render PostgreSQL URL
WEBHOOK_HOST = os.getenv('RENDER_EXTERNAL_URL')   # Render avtomatik beradi
PORT         = int(os.getenv("PORT", 10000))
CHANNEL_ID   = "@abdujalils"
WEBHOOK_PATH = "/webhook"

# Xavfsizlik tekshiruvi
missing = []
if not API_TOKEN:    missing.append("BOT_TOKEN")
if not GROQ_API_KEY: missing.append("GROQ_API_KEY")
if not DATABASE_URL: missing.append("DATABASE_URL")
if missing:
    logger.critical(f"❌ Quyidagi env variable'lar sozlanmagan: {', '.join(missing)}")
    sys.exit(1)

try:
    ADMIN_ID = int(ADMIN_ID) if ADMIN_ID else 0
except ValueError:
    logger.warning("⚠️ ADMIN_ID noto'g'ri formatda.")
    ADMIN_ID = 0

WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else None

# Global obyektlar
client = AsyncGroq(api_key=GROQ_API_KEY)
bot    = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp     = Dispatcher(storage=MemoryStorage())

# --- 2. HOLATLAR (STATES) ---
class UserStates(StatesGroup):
    waiting_for_payment  = State()
    waiting_for_topic    = State()
    waiting_package_choice = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

# --- 3. MULTILINGUAL KONTENT ---
LANGS = {
    'uz': {
        'welcome':           "✨ **Slide Master AI Bot**\n\nProfessional taqdimotlar yaratuvchi sun'iy intellekt!\n\n👇 Quyidagi menyudan kerakli bo'limni tanlang:",
        'btns':              ["💎 Tariflar", "📊 Kabinet", "🤝 Taklif qilish", "📚 Qo'llanma", "🌐 Til / Language"],
        'sub_err':           "🔒 **Botdan foydalanish cheklangan!**\n\nDavom etish uchun rasmiy kanalimizga obuna bo'ling:",
        'tarif':             "💎 **TAQDIMOT NARXLARI:**\n\n⚡ **1 ta Slayd:** 990 so'm\n🔥 **5 ta Slayd:** 2,999 so'm\n👑 **VIP Premium (Cheksiz):** 5,999 so'm\n\n💳 **To'lov kartasi:** `9860230107924485`\n👤 **Karta egasi:** Abdujalil A.\n\n📸 *To'lov chekini shu yerga yuboring va paketni tanlang:*",
        'choose_package':    "🛒 **Paketni tanlang:**",
        'wait':              "🧠 **AI ishlamoqda...**\n\nSlayd tuzilishi generatsiya qilinmoqda. 30-60 soniya vaqt oladi.",
        'done':              "✅ **Taqdimot tayyor!**\n\nFaylni ochish uchun PowerPoint yoki WPS Office ishlating.",
        'no_bal':            "⚠️ **Balans yetarli emas!**\n\nHisobni to'ldiring yoki do'stlaringizni taklif qiling.",
        'cancel':            "❌ Bekor qilish",
        'ref_text':          "🚀 **DO'STLARINGIZNI TAKLIF QILING**\n\n",
        'lang_name':         "🇺🇿 O'zbekcha",
        'gen_prompt':        "Mavzu: {topic}. Nechta slayd kerak?",
        'btn_check':         "✅ Obunani tekshirish",
        'btn_join':          "📢 Kanalga qo'shilish",
        'error':             "⚠️ Xatolik yuz berdi. Iltimos qayta urinib ko'ring.",
        'payment_sent':      "✅ Chek adminga yuborildi. Tez orada javob beriladi.\n\n📋 *To'lov tasdiqlangandan so'ng paket aktivlashtiriladi.*",
        'admin_panel':       "🛠 **Admin panel**\n\nTanlang:",
        'broadcast_start':   "📢 Reklama xabarini yuboring (text/photo/video):",
        'broadcast_canceled':"❌ Bekor qilindi.",
        'broadcast_sent':    "✅ Xabar {count} ta foydalanuvchiga yuborildi.",
        'help_text':         "📚 **QO'LLANMA**\n\n1️⃣ Kanalga obuna bo'ling\n2️⃣ Mavzu yozing va slayd sonini tanlang\n3️⃣ AI prezentatsiya yaratadi\n4️⃣ PowerPoint yoki WPS Office'da oching\n\n🤝 Har bir do'stingiz uchun +1 slayd bonus!",
        'package_btns':      ["1️⃣ 1 ta Slayd", "5️⃣ 5 ta Slayd", "👑 VIP Premium"],
        'balance_added':     "💰 **Balans to'ldirildi!**\n\nHisobingizga **{amount} ta slayd** qo'shildi!",
        'premium_activated': "👑 **Tabriklaymiz!**\nVIP Premium (cheksiz) statusga o'tdingiz!\nEndi cheksiz slayd yaratishingiz mumkin!",
    },
    'ru': {
        'welcome':           "✨ **Slide Master AI Bot**\n\nИИ для создания профессиональных презентаций!\n\n👇 Выберите раздел из меню:",
        'btns':              ["💎 Тарифы", "📊 Кабинет", "🤝 Пригласить", "📚 Инструкция", "🌐 Til / Language"],
        'sub_err':           "🔒 **Доступ ограничен!**\n\nПодпишитесь на наш канал для продолжения:",
        'tarif':             "💎 **ТАРИФЫ:**\n\n⚡ **1 Слайд:** 990 сум\n🔥 **5 Слайдов:** 2,999 сум\n👑 **VIP Premium (Безлимит):** 5,999 сум\n\n💳 **Карта:** `9860230107924485`\n👤 **Владелец:** Abdujalil A.\n\n📸 *Отправьте скриншот чека и выберите пакет:*",
        'choose_package':    "🛒 **Выберите пакет:**",
        'wait':              "🧠 **AI работает...**\n\nГенерируем структуру. 30-60 секунд.",
        'done':              "✅ **Презентация готова!**\n\nИспользуйте PowerPoint или WPS Office.",
        'no_bal':            "⚠️ **Недостаточно баланса!**\n\nПополните счет или пригласите друзей.",
        'cancel':            "❌ Отмена",
        'ref_text':          "🚀 **ПРИГЛАСИТЕ ДРУЗЕЙ**\n\n",
        'lang_name':         "🇷🇺 Русский",
        'gen_prompt':        "Тема: {topic}. Сколько слайдов нужно?",
        'btn_check':         "✅ Проверить подписку",
        'btn_join':          "📢 Подписаться",
        'error':             "⚠️ Произошла ошибка. Попробуйте снова.",
        'payment_sent':      "✅ Чек отправлен администратору.\n\n📋 *После подтверждения пакет будет активирован.*",
        'admin_panel':       "🛠 **Админ панель**\n\nВыберите:",
        'broadcast_start':   "📢 Отправьте рекламное сообщение (text/photo/video):",
        'broadcast_canceled':"❌ Отменено.",
        'broadcast_sent':    "✅ Сообщение отправлено {count} пользователям.",
        'help_text':         "📚 **ИНСТРУКЦИЯ**\n\n1️⃣ Подпишитесь на канал\n2️⃣ Напишите тему и выберите количество слайдов\n3️⃣ AI создаст презентацию\n4️⃣ Откройте в PowerPoint или WPS Office\n\n🤝 +1 слайд за каждого приглашенного!",
        'package_btns':      ["1️⃣ 1 Слайд", "5️⃣ 5 Слайдов", "👑 VIP Premium"],
        'balance_added':     "💰 **Баланс пополнен!**\n\nДобавлено **{amount} слайдов**!",
        'premium_activated': "👑 **Поздравляем!**\nВы на VIP Premium! Создавайте неограниченное количество слайдов!",
    },
    'en': {
        'welcome':           "✨ **Slide Master AI Bot**\n\nAI-powered professional presentation generator!\n\n👇 Choose a section from the menu:",
        'btns':              ["💎 Pricing", "📊 Profile", "🤝 Invite", "📚 Guide", "🌐 Til / Language"],
        'sub_err':           "🔒 **Access Restricted!**\n\nPlease subscribe to our channel to continue:",
        'tarif':             "💎 **PRICING:**\n\n⚡ **1 Slide:** 990 UZS\n🔥 **5 Slides:** 2,999 UZS\n👑 **VIP Premium (Unlimited):** 5,999 UZS\n\n💳 **Card:** `9860230107924485`\n👤 **Owner:** Abdujalil A.\n\n📸 *Send receipt screenshot here and choose package:*",
        'choose_package':    "🛒 **Choose package:**",
        'wait':              "🧠 **AI is thinking...**\n\nGenerating structure and design. 30-60 seconds.",
        'done':              "✅ **Presentation ready!**\n\nOpen with PowerPoint or WPS Office.",
        'no_bal':            "⚠️ **Insufficient balance!**\n\nTop up or invite friends for free slides.",
        'cancel':            "❌ Cancel",
        'ref_text':          "🚀 **INVITE YOUR FRIENDS**\n\n",
        'lang_name':         "🇬🇧 English",
        'gen_prompt':        "Topic: {topic}. How many slides needed?",
        'btn_check':         "✅ Check Subscription",
        'btn_join':          "📢 Join Channel",
        'error':             "⚠️ An error occurred. Please try again.",
        'payment_sent':      "✅ Receipt sent to admin.\n\n📋 *Package will be activated after payment confirmation.*",
        'admin_panel':       "🛠 **Admin Panel**\n\nSelect:",
        'broadcast_start':   "📢 Send broadcast message (text/photo/video):",
        'broadcast_canceled':"❌ Canceled.",
        'broadcast_sent':    "✅ Message sent to {count} users.",
        'help_text':         "📚 **GUIDE**\n\n1️⃣ Subscribe to channel\n2️⃣ Write topic and select slide count\n3️⃣ AI creates presentation\n4️⃣ Open in PowerPoint or WPS Office\n\n🤝 +1 slide bonus per invited friend!",
        'package_btns':      ["1️⃣ 1 Slide", "5️⃣ 5 Slides", "👑 VIP Premium"],
        'balance_added':     "💰 **Balance topped up!**\n\n**{amount} slides** added to your account!",
        'premium_activated': "👑 **Congratulations!**\nYou're now VIP Premium! Create unlimited slides!",
    }
}

# --- 4. PostgreSQL DATABASE MANAGER ---
class Database:
    def __init__(self, dsn: str):
        self.dsn  = dsn
        self.pool = None  # asyncpg connection pool

    async def init(self):
        # SSL sertifikat tekshiruvsiz ulanish (Render PostgreSQL uchun)
        self.pool = await asyncpg.create_pool(
            self.dsn,
            ssl='require',
            min_size=2,
            max_size=10
        )
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id          BIGINT PRIMARY KEY,
                    username    TEXT,
                    first_name  TEXT,
                    last_name   TEXT,
                    lang        TEXT    DEFAULT 'uz',
                    is_premium  INTEGER DEFAULT 0,
                    balance     INTEGER DEFAULT 2,
                    invited_by  BIGINT,
                    created_at  TIMESTAMP DEFAULT NOW(),
                    last_active TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS referrals (
                    id          SERIAL PRIMARY KEY,
                    referrer_id BIGINT,
                    referred_id BIGINT UNIQUE,
                    bonus_given INTEGER DEFAULT 0,
                    created_at  TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id            SERIAL PRIMARY KEY,
                    user_id       BIGINT,
                    amount        INTEGER,
                    package_type  TEXT,
                    screenshot_id TEXT,
                    status        TEXT DEFAULT 'pending',
                    created_at    TIMESTAMP DEFAULT NOW()
                )
            """)
        logger.info("✅ PostgreSQL baza tayyor.")

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def get_user(self, user_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)

    async def add_user(self, user_id, username, first_name, last_name, referrer_id=None):
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO users (id, username, first_name, last_name, invited_by, balance)
                    VALUES ($1, $2, $3, $4, $5, 2)
                """, user_id, username, first_name, last_name, referrer_id)
                if referrer_id:
                    await conn.execute("""
                        INSERT INTO referrals (referrer_id, referred_id)
                        VALUES ($1, $2) ON CONFLICT (referred_id) DO NOTHING
                    """, referrer_id, user_id)
                return True
            except asyncpg.UniqueViolationError:
                await conn.execute(
                    "UPDATE users SET last_active = NOW() WHERE id = $1", user_id
                )
                return False

    async def update_balance(self, user_id: int, amount: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET balance = balance + $1 WHERE id = $2", amount, user_id
            )

    async def set_premium(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET is_premium = 1 WHERE id = $1", user_id
            )

    async def update_lang(self, user_id: int, lang: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET lang = $1 WHERE id = $2", lang, user_id
            )

    async def get_referral_count(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            res = await conn.fetchval(
                "SELECT COUNT(*) FROM referrals WHERE referrer_id = $1", user_id
            )
            return res or 0

    async def get_all_users(self):
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT id FROM users")

    async def get_stats(self):
        async with self.pool.acquire() as conn:
            row     = await conn.fetchrow("SELECT COUNT(*) AS total_users, COALESCE(SUM(balance),0) AS total_slides FROM users")
            premium = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_premium = 1")
            return {
                'total_users':   row['total_users'],
                'total_slides':  row['total_slides'],
                'premium_users': premium
            }

    async def add_payment(self, user_id, amount, package_type, screenshot_id):
        async with self.pool.acquire() as conn:
            return await conn.fetchval("""
                INSERT INTO payments (user_id, amount, package_type, screenshot_id)
                VALUES ($1, $2, $3, $4) RETURNING id
            """, user_id, amount, package_type, screenshot_id)

db = Database(DATABASE_URL)

# --- 5. PPTX GENERATOR ---
def clean_json_string(text: str) -> str:
    try:
        m = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if m:
            return m.group(1)
        start = text.find('{')
        end   = text.rfind('}')
        if start != -1 and end != -1:
            return text[start:end + 1]
        return text
    except Exception as e:
        logger.error(f"JSON cleaning error: {e}")
        return text

def xml_escape(s: str) -> str:
    return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

def create_presentation_file(topic: str, json_data: str, uid: int) -> str:
    os.makedirs("slides", exist_ok=True)
    timestamp  = int(time.time())
    safe_topic = re.sub(r'[^\w\s-]', '', topic)[:30].strip()
    pptx_path  = f"slides/{safe_topic}_{uid}_{timestamp}.pptx"

    try:
        cleaned = clean_json_string(json_data)
        data    = json.loads(cleaned)
        slides  = data.get('slides', [])

        # Slide content types
        slide_ct = "\n".join([
            f'    <Override PartName="/ppt/slides/slide{i+1}.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for i in range(len(slides))
        ])

        # Presentation relationships
        slide_rels = "\n".join([
            f'    <Relationship Id="rId{i+1}" '
            f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
            f'Target="slides/slide{i+1}.xml"/>'
            for i in range(len(slides))
        ])

        # Slide ID list
        slide_ids = "\n".join([
            f'        <p:sldId id="{256 + i}" r:id="rId{i+1}"/>'
            for i in range(len(slides))
        ])

        with zipfile.ZipFile(pptx_path, 'w', zipfile.ZIP_DEFLATED) as pptx:
            pptx.writestr('[Content_Types].xml', f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
    <Default Extension="xml"  ContentType="application/xml"/>
    <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
{slide_ct}
</Types>""")

            pptx.writestr('_rels/.rels', """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>""")

            pptx.writestr('ppt/_rels/presentation.xml.rels', f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{slide_rels}
</Relationships>""")

            pptx.writestr('ppt/presentation.xml', f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
    <p:sldMasterIdLst/>
    <p:sldIdLst>
{slide_ids}
    </p:sldIdLst>
    <p:sldSz cx="9144000" cy="6858000"/>
    <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>""")

            for i, slide in enumerate(slides):
                title  = xml_escape(slide.get('title', f'Slide {i+1}'))
                points = slide.get('points', [])
                if isinstance(points, str):
                    points = [points]

                points_xml = "".join([
                    f'\n                <a:p><a:r><a:t>• {xml_escape(p)}</a:t></a:r></a:p>'
                    for p in points
                ])

                pptx.writestr(f'ppt/slides/slide{i+1}.xml', f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
    <p:cSld>
        <p:spTree>
            <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
            <p:grpSpPr/>
            <p:sp>
                <p:nvSpPr>
                    <p:cNvPr id="2" name="Title"/>
                    <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
                    <p:nvPr><p:ph type="title"/></p:nvPr>
                </p:nvSpPr>
                <p:spPr/>
                <p:txBody>
                    <a:bodyPr/><a:lstStyle/>
                    <a:p><a:r><a:rPr lang="uz-UZ" b="1"/><a:t>{title}</a:t></a:r></a:p>
                </p:txBody>
            </p:sp>
            <p:sp>
                <p:nvSpPr>
                    <p:cNvPr id="3" name="Content"/>
                    <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
                    <p:nvPr><p:ph idx="1"/></p:nvPr>
                </p:nvSpPr>
                <p:spPr/>
                <p:txBody>
                    <a:bodyPr/><a:lstStyle/>{points_xml}
                </p:txBody>
            </p:sp>
        </p:spTree>
    </p:cSld>
</p:sld>""")

                pptx.writestr(f'ppt/slides/_rels/slide{i+1}.xml.rels',
                    """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>""")

        logger.info(f"✅ PPTX yaratildi: {pptx_path}")
        return pptx_path

    except Exception as e:
        logger.error(f"PPTX yaratishda xato: {e}", exc_info=True)
        # Fallback: TXT fayl
        txt_path = f"slides/fallback_{uid}_{int(time.time())}.txt"
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(f"Presentation: {topic}\n{'='*50}\n\n")
            try:
                slides = json.loads(clean_json_string(json_data)).get('slides', [])
                for idx, slide in enumerate(slides):
                    f.write(f"Slide {idx+1}: {slide.get('title','')}\n{'-'*30}\n")
                    for p in (slide.get('points', []) if isinstance(slide.get('points'), list) else [slide.get('points','')]):
                        f.write(f"  • {p}\n")
                    f.write("\n")
            except Exception:
                f.write(f"Topic: {topic}\nTime: {datetime.now()}\n")
        return txt_path

# --- 6. HELPER FUNCTIONS ---
async def check_sub(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception as e:
        logger.warning(f"Kanal tekshiruvi xatosi: {e}")
        return False  # Xavfsizlik uchun False

async def send_sub_message(message: types.Message, lang: str):
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=LANGS[lang]['btn_join'], url=f"https://t.me/{CHANNEL_ID[1:]}")],
        [InlineKeyboardButton(text=LANGS[lang]['btn_check'], callback_data="check_sub")]
    ])
    await message.answer(f"{LANGS[lang]['sub_err']}\n\n{CHANNEL_ID}", reply_markup=ikb)

async def show_main_menu(message: types.Message, lang: str):
    b  = LANGS[lang]['btns']
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=b[0]), KeyboardButton(text=b[1])],
            [KeyboardButton(text=b[2]), KeyboardButton(text=b[3])],
            [KeyboardButton(text=b[4])]
        ],
        resize_keyboard=True
    )
    await message.answer(LANGS[lang]['welcome'], reply_markup=kb)

def remove_temp_file(path: str):
    try:
        os.remove(path)
    except Exception as e:
        logger.warning(f"Temp faylni o'chirishda xato: {e}")

# --- 7. HANDLERLAR ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message, command: CommandObject, state: FSMContext):
    await state.clear()
    user    = message.from_user
    user_id = user.id

    referrer_id = None
    if command.args and command.args.isdigit():
        ref = int(command.args)
        if ref != user_id:
            referrer_id = ref

    is_new = await db.add_user(user_id, user.username, user.first_name, user.last_name, referrer_id)

    if is_new and referrer_id:
        await db.update_balance(referrer_id, 1)
        try:
            ref_data = await db.get_user(referrer_id)
            await bot.send_message(
                referrer_id,
                "🎉 **Tabriklaymiz!**\nSizning havolangiz orqali yangi foydalanuvchi qo'shildi.\n💰 Hisobingizga **+1 slayd** qo'shildi!"
            )
        except Exception as e:
            logger.error(f"Referal bonus yuborishda xato: {e}")

    user_data = await db.get_user(user_id)
    lang      = user_data['lang'] if user_data else 'uz'

    if not await check_sub(user_id):
        return await send_sub_message(message, lang)

    await show_main_menu(message, lang)

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    uid = callback.from_user.id
    if await check_sub(uid):
        await callback.message.delete()
        user = await db.get_user(uid)
        if not user:
            u = callback.from_user
            await db.add_user(uid, u.username, u.first_name, u.last_name)
            user = await db.get_user(uid)
        lang = user['lang'] if user else 'uz'
        await show_main_menu(callback.message, lang)
    else:
        await callback.answer("❌ Hali a'zo bo'lmadingiz!", show_alert=True)

@dp.callback_query(F.data.startswith("lang_"))
async def change_language(callback: CallbackQuery):
    lang_code = callback.data.split("_")[1]
    uid       = callback.from_user.id
    if lang_code in LANGS:
        await db.update_lang(uid, lang_code)
        await callback.answer(f"Til {LANGS[lang_code]['lang_name']} ga o'zgartirildi!")
        user = await db.get_user(uid)
        l    = user['lang'] if user else 'uz'
        await show_main_menu(callback.message, l)
    else:
        await callback.answer("❌ Noto'g'ri til kodi!")

@dp.message(F.text)
async def main_handler(message: types.Message, state: FSMContext):
    uid  = message.from_user.id
    user = await db.get_user(uid)
    if not user:
        return

    l    = user['lang']
    btns = LANGS[l]['btns']
    text = message.text

    if text == btns[0]:  # Tariflar
        package_btns = LANGS[l]['package_btns']
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=package_btns[0]), KeyboardButton(text=package_btns[1])],
                [KeyboardButton(text=package_btns[2])],
                [KeyboardButton(text=LANGS[l]['cancel'])]
            ],
            resize_keyboard=True
        )
        await message.answer(LANGS[l]['tarif'], reply_markup=kb)
        await state.set_state(UserStates.waiting_package_choice)

    elif text == btns[1]:  # Kabinet
        status    = "⭐ VIP PREMIUM" if user['is_premium'] else "👤 Oddiy"
        ref_count = await db.get_referral_count(uid)
        msg = (
            f"📊 **SHAXSIY KABINET**\n\n"
            f"👤 Ism: {user['first_name'] or 'Noma\\'lum'}\n"
            f"🆔 ID: `{uid}`\n"
            f"💰 Balans: **{user['balance']} slayd**\n"
            f"👥 Taklif qilingan: **{ref_count} ta**\n"
            f"🏷 Status: **{status}**\n"
            f"📅 Ro'yxatdan o'tgan: {str(user['created_at'])[:10] if user['created_at'] else 'Noma\\'lum'}"
        )
        await message.answer(msg)

    elif text == btns[2]:  # Taklif
        bot_info = await bot.get_me()
        link     = f"https://t.me/{bot_info.username}?start={uid}"
        count    = await db.get_referral_count(uid)
        share_text = (
            f"🔥 DO'STLARINGIZNI TAKLIF QILING VA BONUS OLING! 🎁\n\n"
            f"🤖 **Slide Master AI Bot** — 60 soniyada professional prezentatsiyalar!\n\n"
            f"✅ 3 xil til: O'zbek, Rus, Ingliz\n"
            f"✅ PowerPoint va WPS Office bilan mos\n\n"
            f"🎁 Har bir do'stingiz uchun **+1 BEPUL slayd**\n\n"
            f"🔗 Sizning havolangiz:\n{link}\n\n"
            f"📊 Statistika:\n👥 Taklif qilingan: **{count} ta** | 🎁 Bonus: **{count} slayd**"
        )
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📤 Ulashish")],
                [KeyboardButton(text=LANGS[l]['cancel'])]
            ],
            resize_keyboard=True
        )
        await message.answer(LANGS[l]['ref_text'] + share_text, reply_markup=kb)

    elif text == btns[3]:  # Qo'llanma
        await message.answer(LANGS[l]['help_text'])

    elif text == btns[4]:  # Til
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz")],
            [InlineKeyboardButton(text="🇷🇺 Русский",   callback_data="lang_ru")],
            [InlineKeyboardButton(text="🇬🇧 English",   callback_data="lang_en")]
        ])
        await message.answer("Tilni tanlang / Select language:", reply_markup=ikb)

    elif text == "📤 Ulashish":
        bot_info = await bot.get_me()
        link     = f"https://t.me/{bot_info.username}?start={uid}"
        await message.answer(f"🔗 Taklif havolangiz:\n\n`{link}`\n\nDo'stlaringizga ulashing!")

    elif text == LANGS[l]['cancel']:
        await state.clear()
        await show_main_menu(message, l)

    elif text == "/admin" and uid == ADMIN_ID:
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Statistika",  callback_data="admin_stats")],
            [InlineKeyboardButton(text="📢 Broadcast",   callback_data="admin_broadcast")]
        ])
        await message.answer(LANGS[l]['admin_panel'], reply_markup=ikb)

    else:  # Slayd mavzusi
        if not user['is_premium'] and user['balance'] <= 0:
            return await message.answer(LANGS[l]['no_bal'])
        await state.update_data(topic=text)
        ikb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📄 7 slayd",  callback_data="gen:7"),
            InlineKeyboardButton(text="📄 10 slayd", callback_data="gen:10"),
            InlineKeyboardButton(text="📄 15 slayd", callback_data="gen:15")
        ]])
        await message.answer(LANGS[l]['gen_prompt'].format(topic=text), reply_markup=ikb)

@dp.message(UserStates.waiting_package_choice)
async def process_package_choice(message: types.Message, state: FSMContext):
    uid          = message.from_user.id
    user         = await db.get_user(uid)
    l            = user['lang']
    package_btns = LANGS[l]['package_btns']
    text         = message.text

    price_map = {
        package_btns[0]: ("1_slide",    990),
        package_btns[1]: ("5_slides",  2999),
        package_btns[2]: ("vip_premium", 5999),
    }

    if text in price_map:
        pkg, amount = price_map[text]
        await state.update_data(chosen_package=pkg, amount=amount)
        await state.set_state(UserStates.waiting_for_payment)
        await message.answer(
            f"💳 To'lov summasi: {amount:,} so'm\n📸 Iltimos, to'lov chekini yuboring.",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=LANGS[l]['cancel'])]],
                resize_keyboard=True
            )
        )
    elif text == LANGS[l]['cancel']:
        await state.clear()
        await show_main_menu(message, l)
    else:
        await message.answer(LANGS[l]['error'])

@dp.message(UserStates.waiting_for_payment, F.photo | F.document)
async def process_payment_screenshot(message: types.Message, state: FSMContext):
    uid  = message.from_user.id
    user = await db.get_user(uid)
    l    = user['lang']
    data = await state.get_data()

    file_id = message.photo[-1].file_id if message.photo else message.document.file_id

    payment_id = await db.add_payment(uid, data.get('amount'), data.get('chosen_package'), file_id)

    if ADMIN_ID:
        try:
            await bot.send_photo(
                ADMIN_ID, file_id,
                caption=(
                    f"🆕 Yangi to'lov!\n\n"
                    f"👤 {user['first_name']} (ID: `{uid}`)\n"
                    f"💳 Paket: {data.get('chosen_package')}\n"
                    f"💰 Summa: {data.get('amount'):,} so'm\n"
                    f"🆔 Payment ID: {payment_id}"
                )
            )
        except Exception as e:
            logger.error(f"Adminga xabar yuborishda xato: {e}")

    await message.answer(LANGS[l]['payment_sent'])
    await state.clear()
    await show_main_menu(message, l)

@dp.message(UserStates.waiting_for_payment, F.text)
async def cancel_payment(message: types.Message, state: FSMContext):
    uid  = message.from_user.id
    user = await db.get_user(uid)
    l    = user['lang']
    if message.text == LANGS[l]['cancel']:
        await state.clear()
        await show_main_menu(message, l)

@dp.callback_query(F.data.startswith("gen:"))
async def generate_slides(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid  = callback.from_user.id
    user = await db.get_user(uid)
    if not user:
        return

    l         = user['lang']
    data      = await state.get_data()
    topic     = data.get('topic')
    if not topic:
        await callback.message.answer(LANGS[l]['error'])
        return

    num_slides = int(callback.data.split(":")[1])

    if not user['is_premium']:
        if user['balance'] < num_slides:
            await callback.message.answer(LANGS[l]['no_bal'])
            return
        await db.update_balance(uid, -num_slides)

    wait_msg = await callback.message.answer(LANGS[l]['wait'])

    try:
        prompt = (
            f'Create a presentation on: "{topic}". '
            f'Return ONLY a valid JSON object:\n'
            f'{{"slides": [{{"title": "...", "points": ["...", "..."]}}]}}\n'
            f'Generate exactly {num_slides} slides. No extra text.'
        )
        response = await client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": "You are a professional presentation creator. Always return valid JSON only, no markdown."},
                {"role": "user",   "content": prompt}
            ],
            temperature=0.7,
            max_tokens=4000
        )

        json_response = response.choices[0].message.content
        file_path     = create_presentation_file(topic, json_response, uid)

        doc = FSInputFile(file_path)
        await callback.message.answer_document(doc, caption=LANGS[l]['done'])
        await wait_msg.delete()
        remove_temp_file(file_path)

    except Exception as e:
        logger.error(f"AI generation error: {e}", exc_info=True)
        if not user['is_premium']:
            await db.update_balance(uid, num_slides)  # Balansni qaytarish
        await callback.message.answer(LANGS[l]['error'])
        await wait_msg.delete()

@dp.callback_query(F.data.startswith("admin_"))
async def admin_panel_handler(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo'q!")
        return

    action = callback.data

    if action == "admin_stats":
        stats = await db.get_stats()
        msg   = (
            f"📊 **Bot statistikasi**\n\n"
            f"👥 Jami foydalanuvchilar: {stats['total_users']}\n"
            f"💰 Jami balans (slaydlar): {stats['total_slides']}\n"
            f"👑 Premium foydalanuvchilar: {stats['premium_users']}"
        )
        await callback.answer()
        await callback.message.answer(msg)

    elif action == "admin_broadcast":
        admin_user = await db.get_user(uid)
        l          = admin_user['lang'] if admin_user else 'uz'
        await callback.message.answer(
            LANGS[l]['broadcast_start'],
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=LANGS[l]['cancel'])]],
                resize_keyboard=True
            )
        )
        await state.set_state(AdminStates.waiting_for_broadcast)
        await callback.answer()

@dp.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid != ADMIN_ID:
        return

    admin_user = await db.get_user(uid)
    l          = admin_user['lang'] if admin_user else 'uz'

    if message.text == LANGS[l]['cancel']:
        await state.clear()
        await message.answer(LANGS[l]['broadcast_canceled'])
        return

    all_users     = await db.get_all_users()
    success_count = 0

    for user in all_users:
        try:
            if message.photo:
                await bot.send_photo(user['id'], message.photo[-1].file_id,
                                     caption=message.caption, parse_mode="Markdown")
            elif message.video:
                await bot.send_video(user['id'], message.video.file_id,
                                     caption=message.caption, parse_mode="Markdown")
            elif message.document:
                await bot.send_document(user['id'], message.document.file_id,
                                        caption=message.caption, parse_mode="Markdown")
            else:
                await bot.send_message(user['id'], message.text, parse_mode="Markdown")
            success_count += 1
            await asyncio.sleep(0.05)  # Telegram rate limit
        except Exception as e:
            logger.error(f"Broadcast xato (user {user['id']}): {e}")

    await message.answer(LANGS[l]['broadcast_sent'].format(count=success_count))
    await state.clear()

# --- 8. HEALTH CHECK (Render uchun) ---
async def health_check(request):
    return web.Response(text="OK", status=200)

# --- 9. ASOSIY FUNKSIYA ---
async def main():
    os.makedirs("slides", exist_ok=True)
    await db.init()

    app = web.Application()
    app.router.add_get('/', health_check)       # Cron job ping uchun
    app.router.add_get('/health', health_check) # Health check

    if WEBHOOK_URL:
        # Webhook rejimi (production)
        logger.info(f"🌐 Webhook rejimi: {WEBHOOK_URL}")
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)

        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
        await site.start()
        logger.info(f"✅ Server {PORT}-portda ishlamoqda")

        # Server to'xtatilmasligi uchun
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()
    else:
        # Polling rejimi (local development)
        logger.info("🔄 Polling rejimi (local)")
        try:
            await dp.start_polling(bot)
        finally:
            await bot.session.close()

    await db.close()
    logger.info("🛑 Bot to'xtatildi.")

if __name__ == "__main__":
    asyncio.run(main())
