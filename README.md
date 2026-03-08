# Proog Trad - بوت التداول الذكي

بوت تداول آلي يعمل 24/7 على أسهم **CIFR** و **IREN** باستخدام Alpaca API.

## الميزات
- تحليل فني بـ 7 مؤشرات (RSI, EMA, MACD, Bollinger, VWAP, ATR, Volume)
- 3 استراتيجيات تداول (Swing أسبوعي، تتبع اتجاه، اختراق)
- 7 طبقات حماية من الخسارة
- لوحة تحكم ويب لحظية (WebSocket)
- تشغيل تلقائي وإعادة تشغيل عند التعطل (Watchdog)

## البنية
```
bot.py               # البوت الرئيسي (وضع CLI)
web_app.py            # واجهة الويب + البوت (FastAPI)
config.py             # الإعدادات
data_engine.py        # محرك البيانات (Alpaca API)
trading_engine.py     # محرك التداول
risk_manager.py       # إدارة المخاطر
technical_analysis.py # التحليل الفني
loss_guardian.py      # حارس الخسارة (7 طبقات)
templates/            # واجهة لوحة التحكم
```

## التشغيل المحلي
```bash
cp .env.example .env
# عدّل .env بمفاتيح Alpaca API

pip install -r requirements.txt
python web_app.py
# افتح http://localhost:8080
```

---

## النشر على Fly.io (مجاني - $0)

### 1. التثبيت
```bash
# Linux/Mac
curl -L https://fly.io/install.sh | sh

# أو عبر brew
brew install flyctl
```

### 2. تسجيل الدخول
```bash
fly auth signup
# أو إذا عندك حساب:
fly auth login
```

### 3. إطلاق التطبيق
```bash
cd "Proog Trad"
fly launch --name proog-trad --region iad --no-deploy
```

### 4. إضافة المفاتيح السرية
```bash
fly secrets set ALPACA_API_KEY=pk_xxxxxxxxxxxxx
fly secrets set ALPACA_SECRET_KEY=sk_xxxxxxxxxxxxx
fly secrets set AUTO_START_TRADING=true
```

### 5. النشر
```bash
fly deploy
```

### 6. فتح لوحة التحكم
```bash
fly open
# أو: https://proog-trad.fly.dev
```

### 7. مراقبة السجلات
```bash
fly logs
```

### التكلفة: $0
- Fly.io يعطي رصيد مجاني $5/شهر
- البوت يستهلك ~$2-3/شهر (shared-cpu-1x, 256MB RAM)
- **إذا تجاوزت الرصيد**: ستحتاج بطاقة ائتمان ولن تتجاوز $5

---

## المتغيرات البيئية

| المتغير | الوصف | القيمة |
|---------|-------|--------|
| `ALPACA_API_KEY` | مفتاح API | مطلوب |
| `ALPACA_SECRET_KEY` | المفتاح السري | مطلوب |
| `AUTO_START_TRADING` | تشغيل تلقائي | `true` |
| `AUTO_RESTART_ON_CRASH` | إعادة تشغيل عند التعطل | `true` |
| `MAX_RESTART_ATTEMPTS` | أقصى محاولات | `10` |
| `PORT` | المنفذ | `8080` |

## دورة عمل البوت
```
ينتظر فتح السوق → يحلل → يشتري → يراقب → يبيع بربح أو يوقف الخسارة → يكرر
```

## ملاحظات
- ابدأ بـ Paper Trading أولاً (`PAPER_TRADING = True` في config.py)
- البوت يعمل فقط خلال ساعات السوق الأمريكي (9:30 AM - 4:00 PM ET)
- خارج ساعات السوق ينتظر تلقائياً
