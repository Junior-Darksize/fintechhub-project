# FintechHub Backend Project 💳

Tushundim, loyihangizning barcha funksional qismlari (Auth, QR-to'lovlar, Karta boshqaruvi va Transfer) qamrab olingan haqiqiy **Full-Scale README.md** varianti kerak. Hamma metodlarni mantiqiy guruhlarga bo'lib, har birining texnik mohiyatini ochib beruvchi eng mukammal variantni tayyorladim.

Buni `README.md` faylingizga to'liqligicha joylashtirishingiz mumkin:

---

# 🛡️ FintechHub: High-Performance P2P & QR Ecosystem

**FintechHub** — Uzcard, Humo va xalqaro to'lov tizimlari uchun banklararo pul o'tkazmalari (P2P), QR-to'lovlar, karta lifecycle boshqaruvi va real vaqtda moliyaviy tahlil ekotizimi.

---

### 🏗️ Arxitektura va Dizayn Patternlari

Loyiha moliya sohasidagi uchta oltin qoidaga asoslanadi: **Xavfsizlik, Tezlik va Audit.**

* **Cache-Aside Pattern:** Karta ma'lumotlarini o'qishda **Redis** keshidan foydalaniladi (30s TTL).
* **Atomic Transactions:** Mablag'lar yo'qolmasligi uchun `@transaction.atomic` va `select_for_update()` mantiqi qo'llanilgan.
* **Soft-Delete Pattern:** Audit uchun kartalar bazadan o'chirilmaydi, faqat `status='deleted'` holatiga o'tkaziladi.
* **QR Processing:** Dinamik va statik QR kodlarni generatsiya qilish va skanerlash mantiqi.

---

### 🛠️ API Metodlari Katalogi (Full Roadmap)

#### 1. 🔐 Avtorizatsiya va Foydalanuvchi (Auth)
| Metod | Vazifasi | Texnik Yondashuv |
| :--- | :--- | :--- |
| `user_login` | Tizimga kirish so'rovi | OTP Generation |
| `user_login_confirm` | Kirishni tasdiqlash | JWT/Session Logic |
| `resend_otp_login` | Kirish kodini qayta yuborish | Rate Limiting |

#### 2. 💳 Karta Boshqaruvi (Card Lifecycle)
| Metod | Vazifasi | Texnik Yondashuv |
| :--- | :--- | :--- |
| `card_add_request` | Yangi karta ulash so'rovi | Linking Logic |
| `card_add_confirm` | Kartani OTP orqali tasdiqlash | SHA-256 Hashing |
| `card_check` | Karta holatini tekshirish | BIN Analysis |
| `card_info` | To'liq karta detallari | Redis Caching |
| `check_balance` | Real-time balans tekshirish | DB Direct Query |
| `card_block_request` | Bloklash uchun OTP so'rash | Context Isolation |
| `card_block_confirm` | Kartani bloklashni yakunlash | Long-term Lock |
| `card_delete_request` | O'chirish so'rovi | Soft-Delete Start |
| `card_delete_confirm` | O'chirishni yakunlash | Status: Deleted |

#### 3. 💸 Pul O'tkazmalari (P2P Transfers)
| Metod | Vazifasi | Texnik Yondashuv |
| :--- | :--- | :--- |
| `transfer_create` | Yangi o'tkazma va OTP yaratish | Audit Logging |
| `transfer_confirm` | Balansni yangilash va yakunlash | Row-level locking |
| `resend_otp` | Kodni qayta yuborish (Max 3x) | Security Block |
| `transfer_cancel` | 60s ichida pulni qaytarish | Reversal Logic |

#### 4. 📱 QR-To'lovlar Tizimi (QR Payments)
| Metod | Vazifasi | Texnik Yondashuv |
| :--- | :--- | :--- |
| `generate_qr_code` | Dinamik to'lov kodini yaratish | QR Generation |
| `scan_qr_details` | QR ichidagi ma'lumotni o'qish | Decryption |
| `confirm_qr_transaction` | QR orqali to'lovni tasdiqlash | Atomic Transaction |

#### 5. 📈 Monitoring va Tahlil
* `get_advanced_insights`: Admin panel uchun 7 va 30 kunlik moliyaviy oqim (Volume) statistikasi.
* `audit_logger`: Barcha harakatlarni loglash va tahlil qilish tizimi.

---

### 📊 Xatoliklar Matritsasi (Error Codes)

1. Tranzaksiya va Karta Xatoliklari
32700 — UNIQUE_EXT_ID: Ext ID noyob bo'lishi shart.

32702 — INSUFFICIENT_FUNDS: Hisobda mablag' yetarli emas.

32704 — INVALID_EXPIRY: Karta amal qilish muddati noto'g'ri.

32705 — CARD_INACTIVE: Karta faol emas.

32708 — LIMIT_EXCEEDED: Miqdor ruxsat etilgan chegaradan katta.

32718 — INVALID_CARD: Karta raqami noto'g'ri.

2. Xavfsizlik va OTP
32710 — OTP_EXPIRED: OTP muddati tugagan.

32711 — ATTEMPTS_EXHAUSTED: Urinishlar soni tugadi.

32712 — WRONG_OTP: Noto'g'ri tasdiqlash kodi.

32716 — TEMP_BLOCKED: Karta vaqtincha bloklangan.

32721 — SECURITY_DELAY: Xavfsizlik choralari: Karta 1 daqiqa davomida pul yuborishdan cheklangan.

3. Foydalanuvchi va Tizim

32720 — PHONE_NOT_LINKED: Telefon raqami kartaga biriktirilmagan.

32724 — USER_LOCKED: Urinishlar soni tugadi. Foydalanuvchi 5 daqiqaga bloklandi.

32725 — BLOCK_REMAINING: Foydalanuvchi bloklangan. Blokdan chiqish vaqti kutilmoqda.

---

### 🛡️ Xavfsizlik Standartlari (Compliance)

1.  **OTP Context Isolation:** Bir maqsad (masalan, Login) uchun kelgan OTP boshqa amal (masalan, Transfer) uchun ishlamaydi.
2.  **PAN Masking:** Karta raqamlari interfeysda faqat `860012****9012` formatida ko'rinadi.
3.  **No-Plaintext Storage:** Tasdiqlash kodlari bazada faqat SHA-256 xeshlari ko'rinishida saqlanadi.
4.  **Audit Trail:** Har bir amaliyot `@audit_logger` dekoratori orqali tizim loglariga muhrlanadi.

---

### ⚙️ Tezkor Ishga Tushirish (Quick Start)

**1. Muhitni sozlash:**
```bash
git clone https://github.com/zuhriddin/fintechhub-core.git
cd fintechhub-core
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**2. Ma'lumotlarni yuklash (Setup Errors):**
```bash
# Xatoliklar bazasini shakllantirish
python manage.py load_error_codes
```

---

### 👨‍💻 Muallif
**Jamoliddin Shamsiddinov** - Backend Architect & Python Expert
* **Loyiha holati:** Active Development 🚀
* **Texnologiyalar:** Django, Redis, PostgreSQL, JSON-RPC.

---
*Loyiha FinTech sohasidagi xalqaro xavfsizlik standartlari (PCI-DSS) asosida ishlab chiqilgan.*