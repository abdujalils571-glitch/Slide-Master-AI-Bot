import logging
import asyncio
import os
import re
import json
import sys
import time
import zipfile
import psycopg2
import psycopg2.extras
from aiohttp import web
from groq import AsyncGroq
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton,
                           InputFile, CallbackQuery)
from aiogram.utils.executor import start_webhook
from datetime import datetime

# --- 1. KONFIGURATSIYA VA LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Environment variables
API_TOKEN    = os.getenv('BOT_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
ADMIN_ID     = os.getenv('ADMIN_ID')
DATABASE_URL = os.getenv('DATABASE_URL')
WEBHOOK_HOST = os.getenv('RENDER_EXTERNAL_URL')
PORT         = int(os.getenv("PORT", 10000))
CHANNEL_ID   = "@abdujalils"
WEBHOOK_PATH = f"/webhook"

# postgres:// → postgresql://
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Xavfsizlik tekshiruvi
missing = []
if not API_TOKEN:    missing.append("BOT_TOKEN")
if not GROQ_API_KEY: missing.append("GROQ_API_KEY")
if not DATABASE_URL: missing.append("DATABASE_URL")
if missing:
    logger.critical(f"❌ Sozlanmagan env vars: {', '.join(missing)}")
    sys.exit(1)

try:
    ADMIN_ID = int(ADMIN_ID) if ADMIN_ID else 0
except ValueError:
    ADMIN_ID = 0

WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else None

# Global obyektlar
client  = AsyncGroq(api_key=GROQ_API_KEY)
storage = MemoryStorage()
bot     = Bot(token=API_TOKEN, parse_mode="Markdown")
dp      = Dispatcher(bot, storage=storage)

# --- 2. HOLATLAR ---
class UserStates(StatesGroup):
    waiting_for_payment    = State()
    waiting_package_choice = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

# --- 3. MULTILINGUAL KONTENT ---
LANGS = {
    'uz': {
        'welcome':            "✨ **Slide Master AI Bot**\n\nProfessional taqdimotlar yaratuvchi sun'iy intellekt!\n\n👇 Quyidagi menyudan kerakli bo'limni tanlang:",
        'btns':               ["💎 Tariflar", "📊 Kabinet", "🤝 Taklif qilish", "📚 Qo'llanma", "🌐 Til / Language"],
        'sub_err':            "🔒 **Botdan foydalanish cheklangan!**\n\nDavom etish uchun rasmiy kanalimizga obuna bo'ling:",
        'tarif':              "💎 **TAQDIMOT NARXLARI:**\n\n⚡ **1 ta Slayd:** 990 so'm\n🔥 **5 ta Slayd:** 2,999 so'm\n👑 **VIP Premium (Cheksiz):** 5,999 so'm\n\n💳 **To'lov kartasi:** `9860230107924485`\n👤 **Karta egasi:** Abdujalil A.\n\n📸 *To'lov chekini shu yerga yuboring va paketni tanlang:*",
        'wait':               "🧠 **AI ishlamoqda...**\n\nSlayd tuzilishi generatsiya qilinmoqda. 30-60 soniya vaqt oladi.",
        'done':               "✅ **Taqdimot tayyor!**\n\nFaylni ochish uchun PowerPoint yoki WPS Office ishlating.",
        'no_bal':             "⚠️ **Balans yetarli emas!**\n\nHisobni to'ldiring yoki do'stlaringizni taklif qiling.",
        'cancel':             "❌ Bekor qilish",
        'ref_text':           "🚀 **DO'STLARINGIZNI TAKLIF QILING**\n\n",
        'lang_name':          "🇺🇿 O'zbekcha",
        'gen_prompt':         "Mavzu: {topic}. Nechta slayd kerak?",
        'btn_check':          "✅ Obunani tekshirish",
        'btn_join':           "📢 Kanalga qo'shilish",
        'error':              "⚠️ Xatolik yuz berdi. Iltimos qayta urinib ko'ring.",
        'payment_sent':       "✅ Chek adminga yuborildi. Tez orada javob beriladi.\n\n📋 *To'lov tasdiqlangandan so'ng paket aktivlashtiriladi.*",
        'admin_panel':        "🛠 **Admin panel**\n\nTanlang:",
        'broadcast_start':    "📢 Reklama xabarini yuboring (text/photo/video):",
        'broadcast_canceled': "❌ Bekor qilindi.",
        'broadcast_sent':     "✅ Xabar {count} ta foydalanuvchiga yuborildi.",
        'help_text':          "📚 **QO'LLANMA**\n\n1️⃣ Kanalga obuna bo'ling\n2️⃣ Mavzu yozing va slayd sonini tanlang\n3️⃣ AI prezentatsiya yaratadi\n4️⃣ PowerPoint yoki WPS Office'da oching\n\n🤝 Har bir do'stingiz uchun +1 slayd bonus!",
        'package_btns':       ["1️⃣ 1 ta Slayd", "5️⃣ 5 ta Slayd", "👑 VIP Premium"],
        'balance_added':      "💰 **Balans to'ldirildi!**\n\nHisobingizga **{amount} ta slayd** qo'shildi!",
        'premium_activated':  "👑 **Tabriklaymiz!**\nVIP Premium statusga o'tdingiz!\nEndi cheksiz slayd yaratishingiz mumkin!",
    },
    'ru': {
        'welcome':            "✨ **Slide Master AI Bot**\n\nИИ для создания профессиональных презентаций!\n\n👇 Выберите раздел из меню:",
        'btns':               ["💎 Тарифы", "📊 Кабинет", "🤝 Пригласить", "📚 Инструкция", "🌐 Til / Language"],
        'sub_err':            "🔒 **Доступ ограничен!**\n\nПодпишитесь на наш канал для продолжения:",
        'tarif':              "💎 **ТАРИФЫ:**\n\n⚡ **1 Слайд:** 990 сум\n🔥 **5 Слайдов:** 2,999 сум\n👑 **VIP Premium (Безлимит):** 5,999 сум\n\n💳 **Карта:** `9860230107924485`\n👤 **Владелец:** Abdujalil A.\n\n📸 *Отправьте скриншот чека и выберите пакет:*",
        'wait':               "🧠 **AI работает...**\n\nГенерируем структуру. 30-60 секунд.",
        'done':               "✅ **Презентация готова!**\n\nИспользуйте PowerPoint или WPS Office.",
        'no_bal':             "⚠️ **Недостаточно баланса!**\n\nПополните счет или пригласите друзей.",
        'cancel':             "❌ Отмена",
        'ref_text':           "🚀 **ПРИГЛАСИТЕ ДРУЗЕЙ**\n\n",
        'lang_name':          "🇷🇺 Русский",
        'gen_prompt':         "Тема: {topic}. Сколько слайдов нужно?",
        'btn_check':          "✅ Проверить подписку",
        'btn_join':           "📢 Подписаться",
        'error':              "⚠️ Произошла ошибка. Попробуйте снова.",
        'payment_sent':       "✅ Чек отправлен администратору.\n\n📋 *После подтверждения пакет будет активирован.*",
        'admin_panel':        "🛠 **Админ панель**\n\nВыберите:",
        'broadcast_start':    "📢 Отправьте рекламное сообщение (text/photo/video):",
        'broadcast_canceled': "❌ Отменено.",
        'broadcast_sent':     "✅ Сообщение отправлено {count} пользователям.",
        'help_text':          "📚 **ИНСТРУКЦИЯ**\n\n1️⃣ Подпишитесь на канал\n2️⃣ Напишите тему и выберите количество слайдов\n3️⃣ AI создаст презентацию\n4️⃣ Откройте в PowerPoint или WPS Office\n\n🤝 +1 слайд за каждого приглашенного!",
        'package_btns':       ["1️⃣ 1 Слайд", "5️⃣ 5 Слайдов", "👑 VIP Premium"],
        'balance_added':      "💰 **Баланс пополнен!**\n\nДобавлено **{amount} слайдов**!",
        'premium_activated':  "👑 **Поздравляем!**\nВы на VIP Premium! Создавайте неограниченное количество слайдов!",
    },
    'en': {
        'welcome':            "✨ **Slide Master AI Bot**\n\nAI-powered professional presentation generator!\n\n👇 Choose a section from the menu:",
        'btns':               ["💎 Pricing", "📊 Profile", "🤝 Invite", "📚 Guide", "🌐 Til / Language"],
        'sub_err':            "🔒 **Access Restricted!**\n\nPlease subscribe to our channel to continue:",
        'tarif':              "💎 **PRICING:**\n\n⚡ **1 Slide:** 990 UZS\n🔥 **5 Slides:** 2,999 UZS\n👑 **VIP Premium (Unlimited):** 5,999 UZS\n\n💳 **Card:** `9860230107924485`\n👤 **Owner:** Abdujalil A.\n\n📸 *Send receipt screenshot here and choose package:*",
        'wait':               "🧠 **AI is thinking...**\n\nGenerating structure and design. 30-60 seconds.",
        'done':               "✅ **Presentation ready!**\n\nOpen with PowerPoint or WPS Office.",
        'no_bal':             "⚠️ **Insufficient balance!**\n\nTop up or invite friends for free slides.",
        'cancel':             "❌ Cancel",
        'ref_text':           "🚀 **INVITE YOUR FRIENDS**\n\n",
        'lang_name':          "🇬🇧 English",
        'gen_prompt':         "Topic: {topic}. How many slides needed?",
        'btn_check':          "✅ Check Subscription",
        'btn_join':           "📢 Join Channel",
        'error':              "⚠️ An error occurred. Please try again.",
        'payment_sent':       "✅ Receipt sent to admin.\n\n📋 *Package will be activated after payment confirmation.*",
        'admin_panel':        "🛠 **Admin Panel**\n\nSelect:",
        'broadcast_start':    "📢 Send broadcast message (text/photo/video):",
        'broadcast_canceled': "❌ Canceled.",
        'broadcast_sent':     "✅ Message sent to {count} users.",
        'help_text':          "📚 **GUIDE**\n\n1️⃣ Subscribe to channel\n2️⃣ Write topic and select slide count\n3️⃣ AI creates presentation\n4️⃣ Open in PowerPoint or WPS Office\n\n🤝 +1 slide bonus per invited friend!",
        'package_btns':       ["1️⃣ 1 Slide", "5️⃣ 5 Slides", "👑 VIP Premium"],
        'balance_added':      "💰 **Balance topped up!**\n\n**{amount} slides** added to your account!",
        'premium_activated':  "👑 **Congratulations!**\nYou're now VIP Premium! Create unlimited slides!",
    }
}

# --- 4. DATABASE (psycopg2) ---
class Database:
    def __init__(self, dsn):
        self.dsn = dsn

    def _connect(self):
        return psycopg2.connect(self.dsn, sslmode='require',
                                cursor_factory=psycopg2.extras.RealDictCursor)

    def _run_sync(self, fn):
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(None, fn)

    async def init(self):
        def _init():
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("""
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
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS referrals (
                        id          SERIAL PRIMARY KEY,
                        referrer_id BIGINT,
                        referred_id BIGINT UNIQUE,
                        created_at  TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("""
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
            conn.commit()
            conn.close()
        await self._run_sync(_init)
        logger.info("✅ PostgreSQL baza tayyor.")

    async def get_user(self, user_id):
        def _get():
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                row = cur.fetchone()
            conn.close()
            return row
        return await self._run_sync(_get)

    async def add_user(self, user_id, username, first_name, last_name, referrer_id=None):
        def _add():
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO users (id, username, first_name, last_name, invited_by)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (user_id, username, first_name, last_name, referrer_id))
                    if referrer_id:
                        cur.execute("""
                            INSERT INTO referrals (referrer_id, referred_id)
                            VALUES (%s, %s) ON CONFLICT (referred_id) DO NOTHING
                        """, (referrer_id, user_id))
                conn.commit()
                conn.close()
                return True
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET last_active = NOW() WHERE id = %s", (user_id,))
                conn.commit()
                conn.close()
                return False
        return await self._run_sync(_add)

    async def update_balance(self, user_id, amount):
        def _upd():
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (amount, user_id))
            conn.commit()
            conn.close()
        await self._run_sync(_upd)

    async def set_premium(self, user_id):
        def _upd():
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET is_premium = 1 WHERE id = %s", (user_id,))
            conn.commit()
            conn.close()
        await self._run_sync(_upd)

    async def update_lang(self, user_id, lang):
        def _upd():
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET lang = %s WHERE id = %s", (lang, user_id))
            conn.commit()
            conn.close()
        await self._run_sync(_upd)

    async def get_referral_count(self, user_id):
        def _get():
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as cnt FROM referrals WHERE referrer_id = %s", (user_id,))
                row = cur.fetchone()
            conn.close()
            return row['cnt'] if row else 0
        return await self._run_sync(_get)

    async def get_all_users(self):
        def _get():
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users")
                rows = cur.fetchall()
            conn.close()
            return rows
        return await self._run_sync(_get)

    async def get_stats(self):
        def _get():
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as total_users, COALESCE(SUM(balance),0) as total_slides FROM users")
                row = cur.fetchone()
                cur.execute("SELECT COUNT(*) as cnt FROM users WHERE is_premium = 1")
                prow = cur.fetchone()
            conn.close()
            return {'total_users': row['total_users'],
                    'total_slides': row['total_slides'],
                    'premium_users': prow['cnt']}
        return await self._run_sync(_get)

    async def add_payment(self, user_id, amount, package_type, screenshot_id):
        def _add():
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO payments (user_id, amount, package_type, screenshot_id)
                    VALUES (%s, %s, %s, %s) RETURNING id
                """, (user_id, amount, package_type, screenshot_id))
                pid = cur.fetchone()['id']
            conn.commit()
            conn.close()
            return pid
        return await self._run_sync(_add)

db = Database(DATABASE_URL)

# --- 5. PPTX GENERATOR ---
def xml_escape(s):
    return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

def clean_json_string(text):
    try:
        m = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if m:
            return m.group(1)
        start = text.find('{')
        end   = text.rfind('}')
        if start != -1 and end != -1:
            return text[start:end+1]
        return text
    except Exception:
        return text

def create_presentation_file(topic, json_data, uid):
    os.makedirs("slides", exist_ok=True)
    timestamp  = int(time.time())
    safe_topic = re.sub(r'[^\w\s-]', '', topic)[:30].strip()
    pptx_path  = f"slides/{safe_topic}_{uid}_{timestamp}.pptx"
    try:
        data   = json.loads(clean_json_string(json_data))
        slides = data.get('slides', [])

        slide_ct = "\n".join([
            f'    <Override PartName="/ppt/slides/slide{i+1}.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for i in range(len(slides))
        ])
        slide_rels_xml = "\n".join([
            f'    <Relationship Id="rId{i+1}" '
            f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
            f'Target="slides/slide{i+1}.xml"/>'
            for i in range(len(slides))
        ])
        slide_ids = "\n".join([
            f'        <p:sldId id="{256+i}" r:id="rId{i+1}"/>'
            for i in range(len(slides))
        ])

        with zipfile.ZipFile(pptx_path, 'w', zipfile.ZIP_DEFLATED) as pptx:
            pptx.writestr('[Content_Types].xml', f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
    <Default Extension="xml" ContentType="application/xml"/>
    <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
{slide_ct}
</Types>""")
            pptx.writestr('_rels/.rels', """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>""")
            pptx.writestr('ppt/_rels/presentation.xml.rels', f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{slide_rels_xml}
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
    <p:cSld><p:spTree>
        <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
        <p:grpSpPr/>
        <p:sp>
            <p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>
            <p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>
                <a:p><a:r><a:rPr lang="uz-UZ" b="1"/><a:t>{title}</a:t></a:r></a:p>
            </p:txBody>
        </p:sp>
        <p:sp>
            <p:nvSpPr><p:cNvPr id="3" name="Content"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph idx="1"/></p:nvPr></p:nvSpPr>
            <p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{points_xml}
            </p:txBody>
        </p:sp>
    </p:spTree></p:cSld>
</p:sld>""")
                pptx.writestr(f'ppt/slides/_rels/slide{i+1}.xml.rels',
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')

        logger.info(f"✅ PPTX: {pptx_path}")
        return pptx_path
    except Exception as e:
        logger.error(f"PPTX xato: {e}", exc_info=True)
        txt = f"slides/fallback_{uid}_{int(time.time())}.txt"
        with open(txt, 'w', encoding='utf-8') as f:
            f.write(f"Topic: {topic}\nTime: {datetime.now()}\n")
        return txt

# --- 6. HELPERS ---
async def check_sub(user_id):
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception as e:
        logger.warning(f"Kanal tekshiruv xato: {e}")
        return False

async def send_sub_message(message: types.Message, lang):
    ikb = InlineKeyboardMarkup().add(
        InlineKeyboardButton(LANGS[lang]['btn_join'], url=f"https://t.me/{CHANNEL_ID[1:]}"),
        InlineKeyboardButton(LANGS[lang]['btn_check'], callback_data="check_sub")
    )
    await message.answer(f"{LANGS[lang]['sub_err']}\n\n{CHANNEL_ID}", reply_markup=ikb)

async def show_main_menu(message: types.Message, lang):
    b  = LANGS[lang]['btns']
    kb = ReplyKeyboardMarkup(resize_keyboard=True).add(
        KeyboardButton(b[0]), KeyboardButton(b[1])
    ).add(
        KeyboardButton(b[2]), KeyboardButton(b[3])
    ).add(KeyboardButton(b[4]))
    await message.answer(LANGS[lang]['welcome'], reply_markup=kb)

def remove_file(path):
    try:
        os.remove(path)
    except Exception:
        pass

# --- 7. HANDLERLAR ---

@dp.message_handler(commands=['start'], state='*')
async def start_cmd(message: types.Message, state: FSMContext):
    await state.finish()
    user    = message.from_user
    user_id = user.id

    # Referal
    args        = message.get_args()
    referrer_id = None
    if args and args.isdigit():
        ref = int(args)
        if ref != user_id:
            referrer_id = ref

    is_new = await db.add_user(user_id, user.username, user.first_name, user.last_name, referrer_id)

    if is_new and referrer_id:
        await db.update_balance(referrer_id, 1)
        try:
            await bot.send_message(referrer_id,
                "🎉 **Tabriklaymiz!**\nSizning havolangiz orqali yangi foydalanuvchi qo'shildi.\n💰 **+1 slayd** qo'shildi!")
        except Exception as e:
            logger.error(f"Referal xabar xato: {e}")

    user_data = await db.get_user(user_id)
    lang      = user_data['lang'] if user_data else 'uz'

    if not await check_sub(user_id):
        return await send_sub_message(message, lang)
    await show_main_menu(message, lang)

@dp.callback_query_handler(lambda c: c.data == 'check_sub', state='*')
async def check_sub_callback(callback: CallbackQuery, state: FSMContext):
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

@dp.callback_query_handler(lambda c: c.data.startswith('lang_'), state='*')
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
        await callback.answer("❌ Noto'g'ri til!")

@dp.message_handler(content_types=types.ContentTypes.TEXT, state='*')
async def main_handler(message: types.Message, state: FSMContext):
    uid  = message.from_user.id
    user = await db.get_user(uid)
    if not user:
        return

    current_state = await state.get_state()
    l    = user['lang']
    btns = LANGS[l]['btns']
    text = message.text

    # Package choice state
    if current_state == 'UserStates:waiting_package_choice':
        package_btns = LANGS[l]['package_btns']
        price_map = {
            package_btns[0]: ("1_slide",     990),
            package_btns[1]: ("5_slides",   2999),
            package_btns[2]: ("vip_premium", 5999),
        }
        if text in price_map:
            pkg, amount = price_map[text]
            await state.update_data(chosen_package=pkg, amount=amount)
            await UserStates.waiting_for_payment.set()
            await message.answer(
                f"💳 To'lov summasi: {amount:,} so'm\n📸 To'lov chekini yuboring.",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(
                    KeyboardButton(LANGS[l]['cancel'])
                )
            )
        elif text == LANGS[l]['cancel']:
            await state.finish()
            await show_main_menu(message, l)
        else:
            await message.answer(LANGS[l]['error'])
        return

    # Payment cancel
    if current_state == 'UserStates:waiting_for_payment':
        if text == LANGS[l]['cancel']:
            await state.finish()
            await show_main_menu(message, l)
        return

    # Admin broadcast state
    if current_state == 'AdminStates:waiting_for_broadcast':
        if text == LANGS[l]['cancel']:
            await state.finish()
            await message.answer(LANGS[l]['broadcast_canceled'])
            return
        all_users     = await db.get_all_users()
        success_count = 0
        for u in all_users:
            try:
                await bot.send_message(u['id'], text, parse_mode="Markdown")
                success_count += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Broadcast xato {u['id']}: {e}")
        await message.answer(LANGS[l]['broadcast_sent'].format(count=success_count))
        await state.finish()
        return

    # Asosiy menu
    if text == btns[0]:  # Tariflar
        package_btns = LANGS[l]['package_btns']
        kb = ReplyKeyboardMarkup(resize_keyboard=True).add(
            KeyboardButton(package_btns[0]), KeyboardButton(package_btns[1])
        ).add(KeyboardButton(package_btns[2])).add(KeyboardButton(LANGS[l]['cancel']))
        await message.answer(LANGS[l]['tarif'], reply_markup=kb)
        await UserStates.waiting_package_choice.set()

    elif text == btns[1]:  # Kabinet
        status    = "⭐ VIP PREMIUM" if user['is_premium'] else "👤 Oddiy"
        ref_count = await db.get_referral_count(uid)
        await message.answer(
            f"📊 **SHAXSIY KABINET**\n\n"
           f"👤 Ism: {user['first_name'] or \"Noma'lum\"}\n"
            f"🆔 ID: `{uid}`\n"
            f"💰 Balans: **{user['balance']} slayd**\n"
            f"👥 Taklif qilingan: **{ref_count} ta**\n"
            f"🏷 Status: **{status}**\n"
            f"📅 Ro'yxatdan o'tgan: {str(user['created_at'])[:10]}"
        )

    elif text == btns[2]:  # Taklif
        bot_me = await bot.get_me()
        link   = f"https://t.me/{bot_me.username}?start={uid}"
        count  = await db.get_referral_count(uid)
        kb = ReplyKeyboardMarkup(resize_keyboard=True).add(
            KeyboardButton("📤 Ulashish")
        ).add(KeyboardButton(LANGS[l]['cancel']))
        await message.answer(
            LANGS[l]['ref_text'] +
            f"🔥 Har bir do'stingiz uchun **+1 BEPUL slayd**!\n\n"
            f"🔗 Havolangiz:\n{link}\n\n"
            f"👥 Taklif qilingan: **{count} ta**",
            reply_markup=kb
        )

    elif text == btns[3]:  # Qo'llanma
        await message.answer(LANGS[l]['help_text'])

    elif text == btns[4]:  # Til
        ikb = InlineKeyboardMarkup().add(
            InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz")
        ).add(
            InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")
        ).add(
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
        )
        await message.answer("Tilni tanlang / Select language:", reply_markup=ikb)

    elif text == "📤 Ulashish":
        bot_me = await bot.get_me()
        link   = f"https://t.me/{bot_me.username}?start={uid}"
        await message.answer(f"🔗 Taklif havolangiz:\n\n`{link}`")

    elif text == LANGS[l]['cancel']:
        await state.finish()
        await show_main_menu(message, l)

    elif text == "/admin" and uid == ADMIN_ID:
        ikb = InlineKeyboardMarkup().add(
            InlineKeyboardButton("📊 Statistika", callback_data="admin_stats"),
            InlineKeyboardButton("📢 Broadcast",  callback_data="admin_broadcast")
        )
        await message.answer(LANGS[l]['admin_panel'], reply_markup=ikb)

    else:  # Slayd mavzusi
        if not user['is_premium'] and user['balance'] <= 0:
            return await message.answer(LANGS[l]['no_bal'])
        await state.update_data(topic=text)
        ikb = InlineKeyboardMarkup().add(
            InlineKeyboardButton("📄 7 slayd",  callback_data="gen:7"),
            InlineKeyboardButton("📄 10 slayd", callback_data="gen:10"),
            InlineKeyboardButton("📄 15 slayd", callback_data="gen:15")
        )
        await message.answer(LANGS[l]['gen_prompt'].format(topic=text), reply_markup=ikb)

@dp.message_handler(content_types=['photo', 'document'], state=UserStates.waiting_for_payment)
async def process_payment_screenshot(message: types.Message, state: FSMContext):
    uid  = message.from_user.id
    user = await db.get_user(uid)
    l    = user['lang']
    data = await state.get_data()

    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    pid     = await db.add_payment(uid, data.get('amount'), data.get('chosen_package'), file_id)

    if ADMIN_ID:
        try:
            await bot.send_photo(
                ADMIN_ID, file_id,
                caption=(
                    f"🆕 Yangi to'lov!\n\n"
                    f"👤 {user['first_name']} (ID: `{uid}`)\n"
                    f"💳 Paket: {data.get('chosen_package')}\n"
                    f"💰 Summa: {data.get('amount'):,} so'm\n"
                    f"🆔 Payment ID: {pid}"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Admin xabar xato: {e}")

    await message.answer(LANGS[l]['payment_sent'])
    await state.finish()
    await show_main_menu(message, l)

@dp.callback_query_handler(lambda c: c.data.startswith('gen:'), state='*')
async def generate_slides(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid  = callback.from_user.id
    user = await db.get_user(uid)
    if not user:
        return

    l          = user['lang']
    data       = await state.get_data()
    topic      = data.get('topic')
    num_slides = int(callback.data.split(":")[1])

    if not topic:
        return await callback.message.answer(LANGS[l]['error'])

    if not user['is_premium']:
        if user['balance'] < num_slides:
            return await callback.message.answer(LANGS[l]['no_bal'])
        await db.update_balance(uid, -num_slides)

    wait_msg = await callback.message.answer(LANGS[l]['wait'])

    try:
        prompt = (
            f'Create a presentation on: "{topic}". '
            f'Return ONLY valid JSON: {{"slides":[{{"title":"...","points":["..."]}}]}} '
            f'Generate exactly {num_slides} slides. No extra text.'
        )
        response = await client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": "You are a presentation creator. Return valid JSON only."},
                {"role": "user",   "content": prompt}
            ],
            temperature=0.7,
            max_tokens=4000
        )
        json_response = response.choices[0].message.content
        file_path     = create_presentation_file(topic, json_response, uid)

        with open(file_path, 'rb') as f:
            await callback.message.answer_document(f, caption=LANGS[l]['done'])
        await wait_msg.delete()
        remove_file(file_path)

    except Exception as e:
        logger.error(f"AI xato: {e}", exc_info=True)
        if not user['is_premium']:
            await db.update_balance(uid, num_slides)
        await callback.message.answer(LANGS[l]['error'])
        await wait_msg.delete()

@dp.callback_query_handler(lambda c: c.data.startswith('admin_'), state='*')
async def admin_callback(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid != ADMIN_ID:
        return await callback.answer("❌ Ruxsat yo'q!")

    if callback.data == "admin_stats":
        stats = await db.get_stats()
        await callback.answer()
        await callback.message.answer(
            f"📊 **Bot statistikasi**\n\n"
            f"👥 Foydalanuvchilar: {stats['total_users']}\n"
            f"💰 Jami balans: {stats['total_slides']}\n"
            f"👑 Premium: {stats['premium_users']}"
        )
    elif callback.data == "admin_broadcast":
        admin = await db.get_user(uid)
        l     = admin['lang'] if admin else 'uz'
        await AdminStates.waiting_for_broadcast.set()
        await callback.answer()
        await callback.message.answer(
            LANGS[l]['broadcast_start'],
            reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(
                KeyboardButton(LANGS[l]['cancel'])
            )
        )

# --- 8. HEALTH CHECK ---
async def health_check(request):
    return web.Response(text="OK", status=200)

# --- 9. STARTUP / SHUTDOWN ---
async def on_startup(dp):
    os.makedirs("slides", exist_ok=True)
    await db.init()
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        logger.info(f"✅ Webhook: {WEBHOOK_URL}")
    else:
        logger.info("🔄 Polling rejimi")

async def on_shutdown(dp):
    await bot.delete_webhook()
    logger.info("🛑 Bot to'xtatildi.")

# --- 10. MAIN ---
if __name__ == "__main__":
    if WEBHOOK_URL:
        app = web.Application()
        app.router.add_get('/', health_check)
        app.router.add_get('/health', health_check)

        from aiogram.webhook.aiohttp_server import SimpleRequestHandler
        # aiogram 2.x uchun
        from aiogram.utils.executor import start_webhook
        start_webhook(
            dispatcher=dp,
            webhook_path=WEBHOOK_PATH,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            skip_updates=True,
            host="0.0.0.0",
            port=PORT,
        )
    else:
        from aiogram import executor
        executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
