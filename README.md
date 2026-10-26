# Emerald Group Bot

بات فارسی مدیریت XP، لول، امتیاز ویژه، لقب، نشان و درخواست ادمینی گروه تلگرام.

## پیش‌نیازها
- Python 3.10 یا جدیدتر
- یک بات ساخته‌شده با BotFather
- سرور دارای اتصال پایدار به Telegram Bot API

## نصب در لینوکس
```bash
mkdir -p emerald_group_bot
cd emerald_group_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python bot.py
```

## نصب در ویندوز PowerShell
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python bot.py
```

اگر PowerShell جلوی فعال‌سازی محیط مجازی را گرفت، فقط برای پنجره فعلی اجرا کن:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

## تنظیمات `.env`
- `BOT_TOKEN`: توکن بات از BotFather
- `OWNER_ID`: شناسه عددی مدیر اصلی تلگرام
- `DATABASE_PATH`: مسیر SQLite
- `XP_PER_MESSAGE`: XP هر پیام واجد شرایط
- `XP_COOLDOWN_SECONDS`: فاصله پیش‌فرض بین پیام‌های XPگیر هر عضو
- تنظیمات اختصاصی هر گروه: XP هر پیام، فاصله پاداش و سقف XP روزانه از پنل مدیریت
- `ADMIN_LEVEL`: لول اولیه درخواست ادمینی

## راه‌اندازی در تلگرام
1. بات را در BotFather بساز و توکن را در `.env` قرار بده.
2. `OWNER_ID` را با شناسه عددی حساب خودت جایگزین کن.
3. برنامه را اجرا کن.
4. بات را به گروه اضافه کن.
5. برای دیدن همه پیام‌های عادی، در BotFather بخش `/setprivacy` را برای بات خاموش کن و در صورت نیاز بات را دوباره به گروه اضافه کن.
6. در گروه `/start` را بزن یا یک پیام بفرست.
7. در چت خصوصی بات `/admin` را بزن.

## فرمان‌ها
- `/start`
- `/help`
- `/me`
- `/rank`
- `/top`
- `/rewards`
- `/league` — لیگ گروهی بر اساس لول
- `/missions` — مأموریت روزانه XP
- `/achievements` — دستاوردهای دائمی
- `/admin_request`
- `/admin` (فقط مدیر اصلی)

## نکات مهم
- XP و امتیاز ویژه مستقل‌اند.
- بات اعضا را از زمان تعاملشان ثبت می‌کند؛ فهرست کامل اعضای قدیمی به‌صورت خودکار در دسترس نیست.
- تأیید درخواست ادمینی تلاش می‌کند مجوزهای ادمینی مشخصی را به عضو بدهد. بات باید در گروه ادمین و دارای مجوز مناسب باشد. مالک گروه باید سیاست ارتقای ادمین را کنترل کند.
- SQLite در پوشه `data` ساخته می‌شود؛ برای پایداری، این پوشه را در دیپلوی حفظ کن.
- جست‌وجوی اعضا مستقیماً در دیتابیس انجام می‌شود و محدود به ۱۰۰ عضو اول نیست. تنظیمات XP و ضداسپم از پنل هر گروه مستقل است.
