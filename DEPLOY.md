# 🚀 Render.com'ga Deploy Qilish Qo'llanmasi

## 📁 GitHub'ga Yuklash

Loyihangizda quyidagi fayllar bo'lishi shart:
```
bot.py              ← asosiy bot fayli
requirements.txt    ← kutubxonalar ro'yxati
```

---

## 🗄️ 1-qadam: PostgreSQL Baza Yaratish

1. [render.com](https://render.com) ga kiring
2. **New** → **PostgreSQL** bosing
3. Quyidagi sozlamalar:
   - **Name:** `slide-master-db`
   - **Region:** `Frankfurt (EU Central)` (yaqin server)
   - **Plan:** `Free`
4. **Create Database** bosing
5. Yaratilgandan keyin **"Internal Database URL"** ni nusxa oling → keyingi qadamda kerak

---

## 🤖 2-qadam: Web Service Yaratish

1. **New** → **Web Service** bosing
2. GitHub repo'ni ulang
3. Sozlamalar:
   - **Name:** `slide-master-bot`
   - **Region:** `Frankfurt (EU Central)` ← baza bilan bir xil!
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
   - **Plan:** `Free`

---

## 🔑 3-qadam: Environment Variables

Web Service ichida **Environment** bo'limiga o'ting va quyidagilarni qo'shing:

| Key | Value | Izoh |
|-----|-------|------|
| `BOT_TOKEN` | `7xxxxxxx:AAF...` | BotFather dan |
| `GROQ_API_KEY` | `gsk_...` | console.groq.com |
| `ADMIN_ID` | `123456789` | Sizning Telegram ID |
| `DATABASE_URL` | `postgresql://...` | 1-qadamdagi URL |

> ⚠️ `RENDER_EXTERNAL_URL` — Render **avtomatik** o'zi qo'shadi, siz qo'shmasangiz ham bo'ladi.

---

## ⏰ 4-qadam: Cron Job (Uyg'otish)

Render Free tier 15 daqiqa faollik bo'lmasa uxlaydi.  
Cron job bilan har 10 daqiqada ping yuborib uyg'otamiz.

1. **New** → **Cron Job** bosing
2. Sozlamalar:
   - **Name:** `keepalive`
   - **Schedule:** `*/10 * * * *` (har 10 daqiqa)
   - **Command:** `curl https://SIZNING-URL.onrender.com/health`
   
   > URL'ni Web Service sahifasidan oling (masalan: `https://slide-master-bot.onrender.com`)

---

## ✅ Tekshirish

Deploy tugagandan keyin:

1. Render loglarini kuzating — `✅ PostgreSQL baza tayyor` va `✅ Server ishlamoqda` ko'rinishi kerak
2. Telegram'da botingizga `/start` yuboring
3. `/health` endpoint'ga browser orqali kiring — `OK` ko'rinishi kerak

---

## ❓ Tez-tez uchraydigan xatolar

| Xato | Sabab | Yechim |
|------|-------|--------|
| `DATABASE_URL not set` | Env var qo'shilmagan | Environment bo'limini tekshiring |
| `SSL error` | DB URL noto'g'ri | Internal URL ishlatilganini tekshiring |
| `Webhook failed` | RENDER_EXTERNAL_URL yo'q | Avtomatik qo'shiladi, bir oz kuting |
| Bot javob bermayapti | Uxlab qolgan | Cron job ishlaётganini tekshiring |
