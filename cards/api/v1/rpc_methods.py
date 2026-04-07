import json
import base64
import hashlib
import random
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from django.utils import timezone
from django.db import transaction
from jsonrpcserver import method, Success
from cards.models import User, OTP, Card, Transfer
from cards.utils import (
    get_rpc_error, send_telegram_message, card_mask, 
    phone_mask, is_luhn_valid, get_live_exchange_rate, mask_name
)
from .decorators import audit_logger
from django.core.cache import cache
import time
from django.utils.translation import gettext as _
import logging
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from cards.models import Error  




# Telegram Bot sozlamalari
TG_TOKEN = "8448513005:AAFCmG5C9a2_3Tbh_bDzoXThUfotsTUlx0E"
TG_CHAT_ID = 1078739901




# Bank standartida logger alohida bo'lim uchun ajratiladi
logger = logging.getLogger('fintech_audit')

@method
@audit_logger
def card_info(context, **params):
    """
    Karta haqidagi to'liq ma'lumotlarni qaytaruvchi RPC metod.
    
    Mantiq:
    1. Karta raqamini keshdan qidiradi (Redis).
    2. Keshda yo'q bo'lsa, bazadan oladi (PostgreSQL) va 30 soniyaga keshga saqlaydi.
    3. Karta BIN kodiga qarab turini (Humo, Uzcard, Visa, Mastercard) aniqlaydi.
    4. Karta raqamini maskalangan holda qaytaradi.
    """
    card_number = params.get("card_number")
    lang = params.get("lang", "uz").lower()
    
    # Karta raqami yuborilmagan bo'lsa xatolik qaytarish
    if not card_number:
        return get_rpc_error(32718, lang=lang)

    # Kesh kalitini shakllantirish
    CACHE_PREFIX = "core:v1:card:info"
    cache_key = f"{CACHE_PREFIX}:{card_number}"
    
    # 1. KESHNI TEKSHIRISH (Cache-Aside pattern)
    try:
        cached_data = cache.get(cache_key)
        if cached_data:
            cached_data["_from_cache"] = True 
            # Keshdan olinganligini log qilish
            logger.info(f" [CACHE HIT] Card: {card_number} | Owner: {cached_data.get('owner_name')}  | Balance: {cached_data['balance']}") 
            return Success(cached_data)
    except Exception as e:
        logger.error(f"Cache Connection Error: {str(e)}")

    # 2. BAZADAN QIDIRISH (Select related bilan ownerni birga tortish)
    card = Card.objects.select_related('owner').filter(card_number=card_number).first()
    
    if not card:
        return get_rpc_error(32704, lang=lang)

    # --- Karta turini BIN kodiga qarab aniqlash mantiqi ---
    c_str = str(card.card_number)
    card_type = "UNKNOWN"
    if c_str.startswith('9860'): 
        card_type = "HUMO"
    elif c_str.startswith(('8600', '5614', '6262', '5445')): 
        card_type = "UZCARD"
    elif c_str.startswith('4'): 
        card_type = "VISA"
    elif c_str.startswith(('51', '52', '53', '54', '55')):
        card_type = "MASTERCARD"

    # Xavfsizlik uchun karta raqamini maskalash (Pan masking)
    masked_number = f"{card.card_number[:6]} {'*' * 4} {'*' * 4} {card.card_number[-4:]}"
    
    # Qaytariladigan ma'lumotlar strukturasi
    data = {
        "card_id": card.id,
        "card_number": masked_number,
        "balance": float(card.balance),
        "currency": "UZS",
        "status": card.status,
        "card_type": card_type,
        "owner_name": card.owner.get_full_name() if card.owner else "N/A",
        "is_sms_active": card.is_sms_enabled,
        "expiry_date": card.expire if hasattr(card, 'expire') else None,
        "_from_cache": False
    }

    # 3. KESHGA YOZISH (Keyingi safar tezroq ishlashi uchun)
    try:
        cache.set(cache_key, data, timeout=30)
        # Bazadan olinganligini va keshga yozilganini log qilish
        logger.info(f" [DB FETCH] Card: {card_number} | Owner: {data['owner_name']} | Balance: {data['balance']} -> Saved to Cache")
    except Exception as e:
        logger.warning(f"Failed to set cache for {card_number}: {str(e)}")
    
    return Success(data)

# --- 1. USER LOGIN ---

# Ushbu metod foydalanuvchi identifikatsiyasini tekshiradi va tizimga kirish uchun 
# 2-faktorli autentifikatsiya (2FA) kodini (OTP) shakllantiradi.
@method
def user_login(context, **params):
    """
    Foydalanuvchi ma'lumotlarini validatsiya qilish va kirish OTP kodini yuborish.

    Mantiq:
    1. Kiruvchi ism, familiya va telefon raqami mavjudligini tekshiradi.
    2. Foydalanuvchini bazadan qidiradi (Ism va familiya harf katta-kichikligiga qaramasdan).
    3. Foydalanuvchi bloklanganlik holatini tekshiradi.
    4. 6 xonali OTP yaratib, uni SHA-256 xeshlash orqali bazada xavfsiz saqlaydi.
    5. Telegram bot orqali kodni yuboradi va maskalangan telefon raqamini qaytaradi.
    """
    # So'rov parametrlaridan til va foydalanuvchi ma'lumotlarini olish
    lang = params.get("lang", "uz").lower()
    first_name = params.get("first_name", "").strip()
    last_name = params.get("last_name", "").strip()
    phone_raw = params.get("phone")

    # Majburiy maydonlar to'ldirilganligini tekshirish (Step 1)
    if not first_name or not last_name or not phone_raw:
        return get_rpc_error(32722, lang=lang)

    # Telefon raqamidagi ortiqcha belgilarni tozalash va foydalanuvchini qidirish (Step 2)
    phone = str(phone_raw).replace("+", "")
    user = User.objects.filter(
        phone_number__icontains=phone,
        first_name__iexact=first_name,
        last_name__iexact=last_name
    ).first()

    # Foydalanuvchi topilmasa 32722 xatoligini qaytarish
    if not user:
        return get_rpc_error(32722, lang=lang)

    # Xavfsizlik: Foydalanuvchi vaqtincha bloklanganligini tekshirish (Step 3)
    if user.blocked_until and timezone.now() < user.blocked_until:
        rem = int((user.blocked_until - timezone.now()).total_seconds())
        return get_rpc_error(32725, lang=lang, extra_msg=f"{rem // 60:02d}:{rem % 60:02d}")

    # OTP yaratish va SHA-256 xavfsizlik standarti bilan xeshlash (Step 4)
    raw_code = str(random.randint(100000, 999999))
    otp_hash = hashlib.sha256(raw_code.encode()).hexdigest()
    
    # OTP obyektini bazada yaratish (Amal qilish muddati 2 daqiqa)
    OTP.objects.create(
        user=user,
        purpose="User Login",
        otp_hash=otp_hash,
        expires_at=timezone.now() + timedelta(minutes=2),
        is_used=False
    )
    
    # Telegram xabarnoma xizmati orqali kodni yuborish (Step 5)
    msg = f"🔐 <b>Kirish kodi</b>\nFoydalanuvchi: {user.get_full_name()}\nKod: <code>{raw_code}</code>"
    send_telegram_message(TG_CHAT_ID, TG_TOKEN, msg)

    # Muvaffaqiyatli javob va maskalangan telefon raqami (Step 6)
    return Success({"status": "otp_sent", "phone": phone_mask(user.phone_number)})






# Ushbu metod foydalanuvchi yuborgan OTP kodini SHA-256 xeshi bilan solishtiradi 
# va muvaffaqiyatli bo'lsa, sessiyani tasdiqlaydi.
@method
@audit_logger
def user_login_confirm(context, **params):
    """
    Foydalanuvchi yuborgan OTP kodini tekshirish va loginni yakunlash.

    Mantiq:
    1. Telefon raqami va OTP kodini qabul qiladi.
    2. Foydalanuvchi bloklanmaganligini va mavjudligini tekshiradi.
    3. Oxirgi faol OTP obyektini bazadan oladi.
    4. verify_otp() orqali kodning to'g'riligini (hashlangan holda) tekshiradi.
    5. Xato urinishlar soni 3 tadan oshsa, foydalanuvchini vaqtincha bloklaydi.
    6. Muvaffaqiyatli bo'lsa, foydalanuvchi ma'lumotlarini qaytaradi.
    """
    # So'rov parametrlarini olish
    lang = params.get("lang", "uz").lower()
    phone_raw = params.get("phone")
    otp_input = params.get("otp")

    # Telefon raqamini tozalash va foydalanuvchini aniqlash (Step 1)
    phone = str(phone_raw).replace("+", "")
    user = User.objects.filter(phone_number__icontains=phone).first()
    if not user: 
        return get_rpc_error(32722, lang=lang)

    # Xavfsizlik: Blokirovka holatini tekshirish (Step 2)
    if user.blocked_until and timezone.now() < user.blocked_until:
        rem = int((user.blocked_until - timezone.now()).total_seconds())
        return get_rpc_error(32725, lang=lang, extra_msg=f"{rem // 60:02d}:{rem % 60:02d}")

    # Foydalanuvchining ishlatilmagan oxirgi OTP kodini olish (Step 3)
    otp_obj = OTP.objects.filter(user=user, purpose="User Login", is_used=False).last()
    if not otp_obj: 
        return get_rpc_error(32710, lang=lang)

    # Kiritilgan kodni hashlangan variant bilan solishtirish (Step 4)
    # verify_otp modeli ichida inputni hashlangan variant bilan solishtiradi
    if otp_obj.verify_otp(otp_input):
        # Muvaffaqiyatli kirishda blokni yechish va foydalanuvchini saqlash (Step 5)
        user.blocked_until = None
        user.save()
        return Success({
            "status": "success",
            "data": {
                "full_name": user.get_full_name(), 
                "phone": phone_mask(user.phone_number)
            }
        })
    else:
        # Xato kod kiritilganda urinishlar sonini tekshirish (Step 6)
        otp_obj.refresh_from_db()
        if otp_obj.try_count >= 3:
            # Urinishlar 3 tadan oshsa, 1 daqiqa (yoki sozlamaga ko'ra) bloklash
            user.blocked_until = timezone.now() + timedelta(minutes=1)
            user.save()
            return get_rpc_error(32724, lang=lang)
        
        # Qolgan urinishlar haqida ma'lumot bilan xato qaytarish
        return get_rpc_error(32712, lang=lang, extra_msg=f" (Urinishlar: {otp_obj.try_count}/3)")






# Ushbu metod avvalgi faol bo'lmagan kodlarni bekor qiladi va foydalanuvchiga 
# yangi xavfsizlik kodini qaytadan yuboradi.
@method
def resend_otp_login(context, **params):
    """
    Login uchun OTP kodini qayta yuborish metodi.

    Mantiq:
    1. Telefon raqami orqali foydalanuvchini aniqlaydi.
    2. Bazadagi ushbu foydalanuvchiga tegishli barcha eski, ishlatilmagan 
       login kodlarini bekor qiladi (is_used=True).
    3. Yangi 6 xonali kod yaratadi va uni SHA-256 xeshi bilan bazaga saqlaydi.
    4. Yangi kodni Telegram xabarnoma xizmati orqali yuboradi.
    """
    # So'rov parametrlarini olish va telefon raqamini formatlash
    lang = params.get("lang", "uz").lower()
    phone_raw = params.get("phone")
    phone = str(phone_raw).replace("+", "")
    
    # Foydalanuvchini bazadan qidirish (Step 1)
    user = User.objects.filter(phone_number__icontains=phone).first()

    if not user: 
        return get_rpc_error(32722, lang=lang)

    # Xavfsizlik: Eski (ishlatilmagan) OTP kodlarini bekor qilish (Step 2)
    # Bu metod bir vaqtning o'zida faqat bitta kod aktiv bo'lishini ta'minlaydi.
    OTP.objects.filter(user=user, purpose="User Login", is_used=False).update(is_used=True)

    # Yangi OTP yaratish va SHA-256 xavfsizlik standarti bilan xeshlash (Step 3)
    raw_code = str(random.randint(100000, 999999))
    otp_hash = hashlib.sha256(raw_code.encode()).hexdigest()
    
    # Yangi OTP obyektini 2 daqiqalik amal qilish muddati bilan yaratish
    OTP.objects.create(
        user=user,
        purpose="User Login",
        otp_hash=otp_hash,
        expires_at=timezone.now() + timedelta(minutes=2),
        is_used=False
    )
    
    # Telegram Gateway orqali yangi kodni foydalanuvchiga yuborish (Step 4)
    send_telegram_message(TG_CHAT_ID, TG_TOKEN, f"🔄 Yangi kod: <code>{raw_code}</code>")

    # Muvaffaqiyatli javob holati
    return Success({"status": "otp_resent"})





# Ushbu metod bank kartasini foydalanuvchi profiliga xavfsiz bog'lash so'rovini qayta ishlaydi.
@method
def card_add_request(context, **params):
    """
    Yangi bank kartasini foydalanuvchi hisobiga bog'lash uchun OTP so'rovi.

    Mantiq:
    1. Karta raqami va telefon raqami mavjudligini bazadan tekshiradi.
    2. Karta holati (Active) va allaqachon bog'lanmaganligini filtrlaydi.
    3. Foydalanuvchi tili (lang) sozlamasini yangilaydi.
    4. "Card Binding" maqsadi bilan yangi SHA-256 xeshlangan OTP yaratadi.
    5. Karta raqamini maskalangan holda Telegram xabarnoma xizmatiga yuboradi.

    Args:
        card_number (str): 16 xonali karta raqami.
        phone (str): Foydalanuvchining tizimdagi telefon raqami.
        lang (str): Xabarnoma tili (uz, ru, en).

    Returns:
        Success: OTP yuborilganligi holati va amal qilish muddati.
        Error: Karta topilmaganda, bloklanganda yoki telefon mos kelmaganda RPC xatosi.
    """
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    phone_raw = params.get("phone")

    # Kiruvchi telefon raqamini formatlash va tozalash
    phone = str(phone_raw).replace("+", "").strip()
    
    # Karta va foydalanuvchini bazadan qidirish (Step 1)
    card = Card.objects.filter(card_number=card_number).first()
    user = User.objects.filter(phone_number__icontains=phone).first()

    # Dastlabki validatsiya: Karta yoki foydalanuvchi mavjudligini tekshirish
    if not card:
        return get_rpc_error(32704, lang=lang) # Karta ma'lumotlari xato
    
    if not user:
        return get_rpc_error(32726, lang=lang) # Telefon raqami xato

    # Xavfsizlik: Bazadagi telefon raqami so'rovdagi raqam bilan mosligini tekshirish (Step 2)
    db_user_phone = str(user.phone_number).replace("+", "").strip()
    if db_user_phone != phone:
        return get_rpc_error(32721, lang=lang) 

    # Karta allaqachon boshqa foydalanuvchiga yoki ushbu foydalanuvchiga bog'langanligini tekshirish (Step 3)
    if card.is_sms_enabled:
        if card.owner == user:
            msgs = {'uz': "Karta allaqachon ulangan.", 'ru': "Карта уже привязана.", 'en': "Card already bound."}
            return Success({"status": "already_bound", "message": msgs.get(lang, msgs['uz'])})
        
        # Agar karta boshqa birovga tegishli bo'lsa, xavfsizlik xatosi
        if card.owner and card.owner != user:
            return get_rpc_error(32705, lang=lang)

    # Karta statusini tekshirish (Deleted yoki Inactive bo'lsa rad etiladi) (Step 4)
    if str(card.status).strip() == 'deleted':
        return get_rpc_error(32718, lang=lang)

    if str(card.status).strip() != 'active':
        return get_rpc_error(32705, lang=lang)

    # Foydalanuvchining tanlagan tilini saqlash
    user.lang = lang
    user.save()

    # --- OTP YARATISH VA HASHLASH (Step 5) ---
    raw_code = str(random.randint(100000, 999999))
    otp_hash = hashlib.sha256(raw_code.encode()).hexdigest()
    
    # Takroriy so'rovlarni oldini olish uchun eski ishlatilmagan binding kodlarini o'chirish
    OTP.objects.filter(user=user, card=card, purpose="Card Binding", is_used=False).delete()
    
    # Yangi xavfsiz OTP obyektini yaratish
    OTP.objects.create(
        user=user,
        card=card,
        purpose="Card Binding",
        otp_hash=otp_hash,
        expires_at=timezone.now() + timedelta(minutes=2),
        is_used=False
    )
    
    # Telegram orqali lokalizatsiya qilingan xabarni yuborish (Step 6)
    otp_msgs = {
        'uz': f"💳 <b>KARTANI ULASH</b>\n\nKarta: <code>{card_mask(card_number)}</code>\nTasdiqlash kodi: <code>{raw_code}</code>",
        'ru': f"💳 <b>ПРИВЯЗКА КАРТЫ</b>\n\nКарта: <code>{card_mask(card_number)}</code>\nКод подтверждения: <code>{raw_code}</code>",
        'en': f"💳 <b>CARD BINDING</b>\n\nCard: <code>{card_mask(card_number)}</code>\nConfirmation code: <code>{raw_code}</code>"
    }
    send_telegram_message(TG_CHAT_ID, TG_TOKEN, otp_msgs.get(lang, otp_msgs['uz']))

    # Muvaffaqiyatli javob (Front-end uchun tayyor ma'lumotlar)
    return Success({
        "status": "otp_sent", 
        "card_number": card_mask(card_number),
        "expires_in": 120
    })






# Ushbu metod karta bog'lash so'rovini tasdiqlaydi, SMS xizmatini faollashtiradi 
# va karta turini (Humo/Uzcard/Visa/MasterCard) aniqlab qaytaradi.
@method
@audit_logger
def card_add_confirm(context, **params):
    """
    Karta bog'lash so'rovini OTP orqali tasdiqlash va yakunlash.

    Mantiq:
    1. Karta raqami va OTP kodini qabul qiladi.
    2. "Card Binding" maqsadi bilan yaratilgan oxirgi ishlatilmagan OTPni qidiradi.
    3. verify_otp() orqali kodning to'g'riligini (hashlangan variantda) tekshiradi.
    4. Muvaffaqiyatli bo'lsa, kartaning 'is_sms_enabled' bayrog'ini True ga o'zgartiradi.
    5. Karta raqamining dastlabki raqamlariga (BIN) qarab uning turini aniqlaydi.
    6. Foydalanuvchiga maskalangan ma'lumotlar va karta balansini qaytaradi.
    """
    # So'rov parametrlarini olish
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    otp_input = params.get("otp")

    # Karta mavjudligini tekshirish (Step 1)
    card = Card.objects.filter(card_number=card_number).first()
    if not card: 
        return get_rpc_error(32718, lang=lang)

    # Oxirgi faol OTP obyektini olish va tekshirish (Step 2)
    otp_obj = OTP.objects.filter(card=card, purpose="Card Binding", is_used=False).last()
    
    # Kod mavjud emasligi yoki xatoligini tekshirish (verify_otp hashni tekshiradi)
    if not otp_obj or not otp_obj.verify_otp(otp_input):
        return get_rpc_error(32712, lang=lang)

    # Karta SMS xizmatini yoqamiz (Step 3)
    # Bu karta tizimga muvaffaqiyatli ulandi degan ma'noni anglatadi
    card.is_sms_enabled = True
    card.save()

    # Karta turini BIN kodlari asosida aniqlash mantiqi (Step 4)
    c_str = str(card_number)
    card_type = "UNKNOWN"
    
    # Milliy va xalqaro to'lov tizimlari filtri
    if c_str.startswith('9860'): 
        card_type = "HUMO"
    elif c_str.startswith(('8600', '5614', '6262', '5445')): 
        card_type = "UZCARD"
    elif c_str.startswith('4'): 
        card_type = "VISA"
    elif c_str.startswith(('51', '52', '53', '54', '55')):
        card_type = "MASTERCARD"

    # Muvaffaqiyatli javob (Step 5)
    # Foydalanuvchi ismi va karta raqami xavfsizlik uchun maskalanadi
    return Success({
        "status": "card_added",
        "data": {
            "card_number": card_mask(card_number),
            "card_type": card_type,
            "card_expire": card.expire,
            "owner_name": mask_name(card.owner.get_full_name()),
            "balance": float(card.balance),
            "is_sms_enabled": card.is_sms_enabled
        }
    })






# Ushbu metod o'tkazma qilishdan oldin qabul qiluvchi kartasini validatsiya qiladi 
# va foydalanuvchiga karta egasining ismini tasdiqlash uchun ko'rsatadi.
@method
def card_check(context, **params):
    """
    Qabul qiluvchi kartasini tekshirish va ma'lumotlarini olish.

    Mantiq:
    1. Luhn algoritmi orqali karta raqami matematik xatolardan xoliligini tekshiradi.
    2. Kartani bazadan qidiradi va uning 'active' holatidaligini ko'radi.
    3. Karta BIN kodiga qarab (Humo, Uzcard, Visa, etc.) turini aniqlaydi.
    4. Karta egasining ism-familiyasini xavfsizlik (Data Privacy) uchun maskalaydi.

    Args:
        receiver_card_number (str): Qabul qiluvchining 16 xonali karta raqami.
        lang (str): Xatoliklar tili.

    Returns:
        Success: Maskalangan ism, karta turi va tasdiqlanganlik holati.
    """
    lang = params.get("lang", "uz").lower()
    r_card_num = params.get("receiver_card_number")

    # 1. Luhn algoritmi bo'yicha matematik tekshirish (Step 1)
    # Bu karta raqami shunchaki raqamlar to'plami emas, haqiqiy karta ekanini bildiradi.
    if not is_luhn_valid(r_card_num):
        return get_rpc_error(32718, lang=lang)

    # 2. Kartani bazadan qidirish (Step 2)
    receiver = Card.objects.filter(card_number=r_card_num).first()

    if not receiver:
        return get_rpc_error(32718, lang=lang)

    # 3. Karta holatini tekshirish (Step 3)
    # O'chirilgan yoki bloklangan kartalarga pul o'tkazib bo'lmaydi.
    if receiver.status == 'deleted':
        return get_rpc_error(32718, lang=lang)

    if receiver.status != 'active':
        return get_rpc_error(32705, lang=lang)

    # --- KARTA TURINI ANIQLASH (Step 4) ---
    c_str = str(r_card_num)
    card_type = "UNKNOWN"
    
    if c_str.startswith('9860'): 
        card_type = "HUMO"
    elif c_str.startswith(('8600', '5614', '6262', '5445')): 
        card_type = "UZCARD"
    elif c_str.startswith('4'): 
        card_type = "VISA"
    elif c_str.startswith(('51', '52', '53', '54', '55')):
        card_type = "MASTERCARD"

    # 4. Karta egasining ism-familiyasini maskalash (Step 5)
    # Maqsad: Foydalanuvchi adashmaganini bilishi kerak, lekin to'liq PII ma'lumot sizmasligi shart.
    if receiver.owner:
        first_name = receiver.owner.first_name
        last_name = receiver.owner.last_name
        # Format: "Zuhriddin J****"
        masked_name = f"{first_name.title()} {last_name[0].title()}****"
    else:
        masked_name = "INCOGNITO"

    # Tasdiqlangan ma'lumotlarni qaytarish
    return Success({
        "receiver_name": masked_name,
        "card_type": card_type,
        "status": "verified"
    })





# Sizning maxfiy kalitingiz
SECRET_KEY = b'FintechHub_Secure_QR_Key_2026_32' 

# ----------------------------------------------------------------
# 0-ETAP: GENERATE QR CODE (Qabul qiluvchi uchun)
# ----------------------------------------------------------------
# Ushbu metod qabul qiluvchining karta ma'lumotlari va to'lov summasini 
# xavfsiz shifrlangan xesh ko'rinishiga o'tkazib beradi.
@method
def generate_qr_code(context, **params):
    """
    Qabul qiluvchi uchun shifrlangan QR-kod xeshini yaratish.

    Mantiq:
    1. Karta raqami va ixtiyoriy ravishda to'lov summasini (amount) qabul qiladi.
    2. Kartaning bazada mavjudligi va 'active' holatidaligini tekshiradi.
    3. Ma'lumotlarni (karta, summa, valyuta, vaqt) JSON formatiga yig'adi.
    4. AES-256 algoritmi va maxfiy kalit (SECRET_KEY) yordamida shifrlaydi.
    5. Shifrlangan baytlarni Base64 formatiga o'tkazib, tayyor xeshni qaytaradi.

    Args:
        card_number (str): Qabul qiluvchining karta raqami.
        amount (decimal, optional): Belgilangan to'lov summasi.
        currency (str): Valyuta kodi (masalan, 860 - UZS).

    Returns:
        Success: {"hash_data": "..."} - Shifrlangan xesh ma'lumoti.
    """
    lang = params.get("lang", "uz").lower()
    card_num = params.get("card_number")
    amount_raw = params.get("amount", 0)
    currency_input = params.get("currency", "860") # Standart: O'zbek so'mi

    # To'lov summasini formatlash (Step 1)
    try:
        amount = Decimal(str(amount_raw))
    except:
        amount = Decimal('0')

    # Qabul qiluvchi kartasini bazadan faqat 'active' holatda qidirish (Step 2)
    card = Card.objects.filter(card_number=card_num, status='active').first()
    if not card:
        return get_rpc_error(32718, lang=lang)

    # Agar summa ko'rsatilgan bo'lsa valyutani belgilash, aks holda bo'sh qoldirish
    fixed_currency = currency_input if amount > 0 else None

    # QR-kod ichiga joylanadigan ma'lumotlar paketi (Payload) (Step 3)
    qr_payload = {
        "receiver_card": card.card_number,
        "fixed_amount": float(amount) if amount > 0 else None,
        "currency": fixed_currency,
        "ts": int(timezone.now().timestamp()) # Yaratilgan vaqti (Anti-replay uchun)
    }

    # --- KRIPTOGRAFIK SHIFRLASH (AES-256-CBC) (Step 4) ---
    try:
        data_str = json.dumps(qr_payload)
        # Yangi AES shifrlovchi obyekt yaratish (CBC rejimi)
        cipher = AES.new(SECRET_KEY, AES.MODE_CBC)
        iv = cipher.iv # Initialization Vector (Xavfsizlik uchun tasodifiy baytlar)
        
        # Ma'lumotni blok o'lchamiga moslab to'ldirish (Padding) va shifrlash
        encrypted_bytes = cipher.encrypt(pad(data_str.encode('utf-8'), AES.block_size))
        
        # IV va shifrlangan ma'lumotni birlashtirib Base64 ga o'tkazish (Step 5)
        hash_data = base64.b64encode(iv + encrypted_bytes).decode('utf-8')
        
        return Success({"hash_data": hash_data})
    except Exception:
        # Kriptografik xatolik yuz bersa, texnik xato qaytarish
        return get_rpc_error(32706, lang=lang)


# ----------------------------------------------------------------
# 1-ETAP: SCAN QR DETAILS (Yuboruvchi skaner qilganda)
# ----------------------------------------------------------------
# Ushbu metod shifrlangan QR xeshini ochadi, vaqt bo'yicha haqiqiyligini tekshiradi 
# va qabul qiluvchi ma'lumotlari bilan birga to'lov limitlarini qaytaradi.
@method
def scan_qr_details(context, **params):
    """
    Shifrlangan QR ma'lumotlarini o'qish va to'lov parametrlarini aniqlash.

    Mantiq:
    1. Base64 formatidagi xeshni dekodlaydi va AES-256 (CBC) orqali parollaydi.
    2. QR-kodning amal qilish muddatini tekshiradi (3 daqiqalik TTL).
    3. Qabul qiluvchi kartasini bazadan qidirib, egasining ma'lumotlarini oladi.
    4. To'lov summasi QR ichida belgilanganligiga qarab limitlarni (min/max) belgilaydi.
    5. Agar summa belgilangan bo'lsa (Fixed), foydalanuvchi uni o'zgartira olmaydi.

    Args:
        hash_data (str): Generatsiya qilingan shifrlangan QR xeshi.
        lang (str): Xatoliklar tili.

    Returns:
        Success: Qabul qiluvchi nomi, karta raqami, summa va limitlar.
    """
    hash_data = params.get("hash_data")
    lang = params.get("lang", "uz").lower()

    try:
        # --- AES DEKODLASH VA DESHIFRLASH (Step 1) ---
        raw_bytes = base64.b64decode(hash_data)
        iv = raw_bytes[:16] # Dastlabki 16 bayt - Initialization Vector
        encrypted_payload = raw_bytes[16:]
        
        cipher = AES.new(SECRET_KEY, AES.MODE_CBC, iv)
        # Ma'lumotni ochish va paddingdan tozalash
        payload = json.loads(unpad(cipher.decrypt(encrypted_payload), AES.block_size).decode('utf-8'))
        
        # --- XAVFSIZLIK: TTL (Time To Live) TEKSHIRUVI (Step 2) ---
        # QR-kod yaratilganidan keyin 180 soniya (3 daqiqa) ichida skaner qilinishi shart.
        # Bu eski QR-kodlarni qayta ishlatish (Replay Attack) xavfini kamaytiradi.
        if int(timezone.now().timestamp()) - payload.get("ts", 0) > 180:
            return get_rpc_error(32706, lang=lang)

        receiver_card_num = payload.get("receiver_card")
        fixed_amount = payload.get("fixed_amount")
        fixed_currency = payload.get("currency")
        
        # Qabul qiluvchi kartasini va uning egasini bazadan olish (Step 3)
        card = Card.objects.filter(card_number=receiver_card_num).select_related('owner').first()
        if not card:
            return get_rpc_error(32718, lang=lang)

        # --- BIZNES MANTIQ: MIN/MAX LIMITLAR (Step 4) ---
        if fixed_amount and fixed_amount > 0:
            # Agar QR-kod aniq bir summa uchun yaratilgan bo'lsa (masalan: do'kon cheki):
            # Foydalanuvchi summani tahrirlay olmaydi (is_fixed=True).
            min_amt = max_amt = fixed_amount
            currency = fixed_currency or "860"
            is_fixed = True
        else:
            # Agar QR-kodda summa bo'lmasa (masalan: shaxsiy QR):
            # Foydalanuvchi ixtiyoriy summa kiritadi, lekin standart limitlar doirasida.
            min_amt = 1000
            max_amt = 20000000
            currency = "860"
            is_fixed = False

        # Ma'lumotlarni UI uchun tayyorlash (Step 5)
        return Success({
            "receiver_name": card.owner.get_full_name() if card.owner else "N/A",
            "receiver_card": receiver_card_num,
            "receiver_status": card.status,
            "amount": float(fixed_amount) if fixed_amount else None, 
            "min_amount": float(min_amt),
            "max_amount": float(max_amt),
            "currency": currency,
            "is_fixed": is_fixed
        })
    except Exception:
        # Dekodlashda xatolik bo'lsa (noto'g'ri xesh yoki kalit)
        return get_rpc_error(32706, lang=lang)

# ----------------------------------------------------------------
# 2-ETAP: CREATE TRANSACTION (Chek tayyorlash)
# Ushbu metod valyuta kursini hisobga olgan holda QR-tranzaksiyani yaratadi 
# va foydalanuvchiga yakuniy to'lov miqdorini (so'mda) ko'rsatadi.
@method
def create_qr_transaction(context, **params):
    """
    Valyuta konvertatsiyasi bilan QR-tranzaksiya yaratish.

    Mantiq:
    1. Kiruvchi ISO raqamli kodlarini (840, 643) harfli kodlarga (USD, RUB) o'giradi.
    2. Markaziy bank yoki tashqi API'dan joriy valyuta kursini oladi.
    3. Kiritilgan summani kursga ko'paytirib, so'mdagi (UZS) haqiqiy qiymatni hisoblaydi.
    4. Jo'natuvchining balansini so'mdagi summa bilan solishtiradi.
    5. Tranzaksiyani 'created' holatida bazaga saqlaydi va chek ma'lumotlarini qaytaradi.

    Args:
        sender_card_number (str): To'lovchi karta raqami.
        amount (Decimal): Tanlangan valyutadagi summa.
        currency (str): ISO valyuta kodi (masalan: 840, 978, 860).

    Returns:
        Success: Tranzaksiya ID, kurs, so'mdagi summa va sana.
    """
    sender_card_num = params.get("sender_card_number")
    receiver_card_num = params.get("receiver_card_number")
    amount = Decimal(str(params.get("amount", 0)))
    currency_code = str(params.get("currency", "860"))
    lang = params.get("lang", "uz").lower()

    # Jo'natuvchi kartasini tekshirish (Step 1)
    sender = Card.objects.filter(card_number=sender_card_num).first()
    if not sender:
        return get_rpc_error(32718, lang=lang)

    # --- VALYUTA KODLARINI FORMATLASH (Step 2) ---
    # API kurs funksiyasi harfli kodlar (USD) bilan ishlagani uchun xarita tuzamiz
    iso_map = {
        "840": "USD",
        "643": "RUB",
        "978": "EUR",
        "860": "UZS"
    }
    target_currency = iso_map.get(currency_code, currency_code).upper()

    # Tashqi xizmatdan jonli kursni olish (Step 3)
    rate_val = get_live_exchange_rate(target_currency)
    rate = Decimal(str(rate_val)) if rate_val else Decimal('1')
    
    # So'mdagi haqiqiy summani hisoblash (Masalan: 10$ * 12,850 = 128,500 so'm)
    sending_amount_uzs = (amount * rate).quantize(Decimal('1.00'))

    # Balans yetarliligini tekshirish (Step 4)
    if sender.balance < sending_amount_uzs:
        return get_rpc_error(32702, lang=lang)

    # Tranzaksiyani yaratish va bazaga saqlash (Step 5)
    transfer = Transfer.objects.create(
        sender_card_number=sender_card_num,
        receiver_card_number=receiver_card_num,
        sending_amount=sending_amount_uzs,
        receiving_amount=sending_amount_uzs,
        state='created', # Tasdiqlashdan oldingi holat
        currency=currency_code,
        ext_id=f"QR-{timezone.now().strftime('%y%m%d%H%M%S')}" # Unikal tashqi ID
    )

    # Chek (Receipt) uchun ma'lumotlarni qaytarish
    return Success({
        "transaction_id": transfer.id,
        "state": "created",
        "sender_card": sender_card_num,
        "receiver_card": receiver_card_num,
        "amount_in_currency": float(amount),
        "currency": currency_code,
        "exchange_rate": float(rate),
        "total_to_pay_uzs": float(sending_amount_uzs),
        "date": timezone.now().strftime("%d.%m.%Y %H:%M")
    })

# ----------------------------------------------------------------
# 3-ETAP: CONFIRM TRANSACTION (Tasdiqlash va Pul yechish)
# ----------------------------------------------------------------
# Ushbu metod yaratilgan tranzaksiyani tasdiqlaydi, pulni hisobdan chiqaradi 
# va foydalanuvchiga yakuniy elektron chekni taqdim etadi.
@method
@audit_logger
@transaction.atomic
def confirm_qr_transaction(context, **params):
    """
    QR-tranzaksiyani yakunlash va pul mablag'larini o'tkazish.

    Mantiq:
    1. Tranzaksiya ID orqali 'created' holatidagi transferni topadi va bloklaydi.
    2. Jo'natuvchi va qabul qiluvchi kartalarini 'select_for_update' orqali bloklaydi (Race condition oldini olish).
    3. Balansni so'mdagi qiymat bilan oxirgi marta tekshiradi.
    4. Jo'natuvchidan pulni ayirib, qabul qiluvchiga qo'shadi (Atomic operation).
    5. Tranzaksiya holatini 'confirmed' ga o'zgartiradi va batafsil chek qaytaradi.
    """
    tr_id = params.get("transaction_id")
    lang = params.get("lang", "uz").lower()

    # --- MA'LUMOTLARNI BLOKLASH (Step 1) ---
    # select_for_update() bazada ushbu qatorni boshqa so'rovlar o'zgartira olmasligi uchun vaqtincha yopib qo'yadi.
    transfer = Transfer.objects.select_for_update().filter(id=tr_id, state='created').first()
    if not transfer:
        return Success({"success": False, "message": "Tranzaksiya topilmadi yoki allaqachon to'langan"})

    # Kartalarni ham bloklaymiz (Step 2)
    sender = Card.objects.select_for_update().filter(card_number=transfer.sender_card_number).first()
    receiver = Card.objects.select_for_update().filter(card_number=transfer.receiver_card_number).first()

    # Balansni bazadagi so'mda saqlangan haqiqiy summa bilan tekshirish (Step 3)
    if sender.balance < transfer.sending_amount:
        return get_rpc_error(32702, lang=lang)

    # --- PUL KO'CHIRISH (ACID tamoyili asosida) (Step 4) ---
    sender.balance -= transfer.sending_amount
    receiver.balance += transfer.receiving_amount
    
    # Ma'lumotlarni saqlash
    sender.save()
    receiver.save()

    # Tranzaksiya statusini muvaffaqiyatli deb belgilash (Step 5)
    transfer.state = 'confirmed'
    transfer.save()

    # YAKUNIY ELEKTRON CHEK (Receipt)
    # Karta raqamlari xavfsizlik uchun maskalangan holda qaytariladi.
    return Success({
        "status": "confirmed",
        "receipt": {
            "transaction_id": transfer.ext_id,
            "status_text": "TO'LOV MUVAFFAQIYATLI",
            "amount_uzs": float(transfer.sending_amount),
            "currency_code": transfer.currency,
            "sender_card": f"{sender.card_number[:6]} **** {sender.card_number[-4:]}",
            "receiver_card": f"{receiver.card_number[:6]} **** {receiver.card_number[-4:]}",
            "receiver_name": receiver.owner.get_full_name() if receiver.owner else "N/A",
            "date_time": timezone.now().strftime("%d.%m.%Y %H:%M:%S")
        }
    })




# Telegram sozlamalari
TOKEN = "8448513005:AAFCmG5C9a2_3Tbh_bDzoXThUfotsTUlx0E"
CHAT_ID = 1078739901
# Ushbu metod pul o'tkazmasi so'rovini qabul qiladi, barcha xavfsizlik 
# filtrlaridan o'tkazadi va tasdiqlash uchun shifrlangan OTP yaratadi.
@method
@audit_logger
def transfer_create(context, **params):
    """
    Pul o'tkazmasi so'rovini yaratish va validatsiya qilish.

    Mantiq:
    1. Valyuta turi va karta raqamlarining matematik to'g'riligini (Luhn) tekshiradi.
    2. Jo'natuvchi va qabul qiluvchi kartalari holatini (Active, Expiry) filtrlaydi.
    3. Jo'natuvchining balansini joriy valyuta kursi bo'yicha (UZSda) hisoblaydi.
    4. Xavfsizlik uchun barcha eski 'created' holatdagi tranzaksiyalarni bekor qiladi.
    5. SHA-256 xeshlangan OTP yaratib, Telegram orqali ko'p tilli xabar yuboradi.
    """
    # 1. Parametrlarni olish va formatlash
    lang = params.get("lang", "uz").lower()
    ext_id = params.get("ext_id")
    s_card_num = params.get("sender_card_number")
    s_card_expiry = params.get("sender_card_expiry")
    r_card_num = params.get("receiver_card_number")
    raw_amount = Decimal(str(params.get("sending_amount", 0)))
    currency = params.get("currency", "UZS").upper()

    # 2. Dastlabki tekshiruvlar: Valyuta va Luhn algoritmi (Step 1)
    allowed_currencies = ['UZS', 'RUB', 'USD']
    if currency not in allowed_currencies:
        return get_rpc_error(32707, lang=lang)

    if not is_luhn_valid(s_card_num) or not is_luhn_valid(r_card_num):
        return get_rpc_error(32718, lang=lang)

    # 3. Kartalarni bazadan qidirish (Step 2)
    sender = Card.objects.filter(card_number=s_card_num).first()
    receiver = Card.objects.filter(card_number=r_card_num).first()

    if not sender or not receiver:
        return get_rpc_error(32718, lang=lang)

    # 4. Karta ma'lumotlarini (Muddati, Statusi, SMS) tekshirish (Step 3)
    if sender.expire != s_card_expiry:
        return get_rpc_error(32704, lang=lang)

    if sender.status != 'active' or receiver.status != 'active':
        return get_rpc_error(32705, lang=lang)

    # SMS-xabarnoma xizmati yoqilganligini tekshirish (Fintech majburiyati)
    if not sender.is_sms_enabled:
        return get_rpc_error(32703, lang=lang)

    # 5. Xavfsizlik: Blokirovka holatini tekshirish (Step 4)
    if sender.blocked_until and timezone.now() < sender.blocked_until:
        rem = int((sender.blocked_until - timezone.now()).total_seconds())
        return get_rpc_error(32716, lang=lang, extra_msg=f"({rem // 60:02d}:{rem % 60:02d})")

    # 6. Balansni tekshirish: Kursga o'girgan holda (Step 5)
    rate = get_live_exchange_rate(currency)
    total_in_uzs = (raw_amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if sender.balance < total_in_uzs:
        return get_rpc_error(32702, lang=lang)

    # 7. ANTI-FRAUD: Eskib qolgan 'created' tranzaksiyalarni bekor qilish (Step 6)
    Transfer.objects.filter(
        sender_card_number=s_card_num, 
        state='created'
    ).update(state='cancelled', updated_at=timezone.now())

    # 8. Yangi Transfer obyektini yaratish (Step 7)
    transfer = Transfer.objects.create(
        ext_id=ext_id,
        sender_card_number=s_card_num,
        receiver_card_number=r_card_num,
        sender_card_expiry=s_card_expiry,
        sending_amount=total_in_uzs,
        currency=currency
    )
    
    # --- OTP YARATISH VA HASHLASH (Step 8) ---
    # 6 xonali kod yaratiladi va faqat uning xeshi bazada saqlanadi
    otp_code = str(random.randint(100000, 999999))
    otp_hash = hashlib.sha256(otp_code.encode()).hexdigest()
    
    OTP.objects.create(
        user=sender.owner,
        card=sender,
        transfer=transfer,
        purpose="Money Transfer",
        otp_hash=otp_hash,
        expires_at=timezone.now() + timedelta(minutes=2),
        is_used=False
    )
    
    # 9. KO'P TILLI TELEGRAM OTP XABARI (Step 9)
    name_hidden = mask_name(sender.owner.get_full_name() if sender.owner else "Mijoz")
    amt_f = f"{raw_amount:,.2f} {currency}"
    s_mask = card_mask(s_card_num)

    otp_msgs = {
        'uz': f"💸 <b>TASDIQLASH KODI</b>\n\nKimdan: <b>{name_hidden}</b>\nKarta: <b>{s_mask}</b>\nMiqdor: <b>{amt_f}</b>\n\nKod: <code>{otp_code}</code>",
        'ru': f"💸 <b>КОД ПОДТВЕРЖДЕНИЯ</b>\n\nОт кого: <b>{name_hidden}</b>\nКарта: <b>{s_mask}</b>\nСумма: <b>{amt_f}</b>\n\nКод: <code>{otp_code}</code>",
        'en': f"💸 <b>CONFIRMATION CODE</b>\n\nFrom: <b>{name_hidden}</b>\nCard: <b>{s_mask}</b>\nAmount: <b>{amt_f}</b>\n\nCode: <code>{otp_code}</code>"
    }

    send_telegram_message(TG_CHAT_ID, TG_TOKEN, otp_msgs.get(lang, otp_msgs['uz']))

    # 10. Muvaffaqiyatli Response qaytarish
    return Success({
        "ext_id": ext_id,
        "state": "created",
        "otp_sent": True,
        "expires_in": 120
    })




# Ushbu metod OTP kodini tekshiradi, xato kiritilganda kartani progressiv bloklaydi 
# va muvaffaqiyatli o'tkazmadan so'ng keshni yangilaydi.
@method
@audit_logger
def transfer_confirm(context, **params):
    """
    OTP kodini tasdiqlash va pul o'tkazmasini yakunlash.

    Mantiq:
    1. Tranzaksiya va kartalarni 'select_for_update' orqali bloklaydi (Race condition oldini olish).
    2. Kartaning bloklanmaganligini tekshiradi (Time-based blocking).
    3. OTP kodining to'g'riligini va amal qilish muddatini (120s) tekshiradi.
    4. Xato kiritilgan taqdirda urinishlar soniga qarab (5, 15, 30 daqiqa) blok qo'yadi.
    5. Muvaffaqiyatli o'tkazmadan so'ng balanslarni yangilaydi va Redis keshini (cache.delete) tozalaydi.

    Args:
        ext_id (str): transfer_create'dan qaytgan unikal ID.
        otp (str): Foydalanuvchi kiritgan 6 xonali tasdiqlash kodi.

    Returns:
        Success: Tranzaksiya holati va batafsil elektron chek.
    """
    lang = params.get("lang", "uz").lower()
    ext_id = params.get("ext_id")
    otp_input = params.get("otp")

    with transaction.atomic():
        # --- 1. MA'LUMOTLARNI BLOKLASH (Isolation Level) ---
        t = Transfer.objects.select_for_update().filter(ext_id=ext_id, state='created').first()
        if not t:
            return get_rpc_error(32706, lang=lang)

        sender_card = Card.objects.select_for_update().filter(card_number=t.sender_card_number).first()
        receiver_card = Card.objects.select_for_update().filter(card_number=t.receiver_card_number).first()

        # --- 2. XAVFSIZLIK: BLOKNI TEKSHIRISH ---
        if sender_card.blocked_until and timezone.now() < sender_card.blocked_until:
            rem = int((sender_card.blocked_until - timezone.now()).total_seconds())
            return get_rpc_error(32716, lang=lang, extra_msg=f"({rem // 60:02d}:{rem % 60:02d})")

        # OTP obyektini olish
        otp_log = OTP.objects.filter(transfer=t, is_used=False).last()
        if not otp_log:
            return get_rpc_error(32710, lang=lang)

        # --- 3. OTP VA VAQT FILTRI ---
        time_passed = (timezone.now() - otp_log.created_at).total_seconds()
        is_otp_correct = otp_log.verify_otp(otp_input)

        if time_passed > 120 or not is_otp_correct:
            t.try_count += 1
            t.save()
            
            # --- PROGRESSIV BLOKLASH LOGIKASI ---
            # Har bir xato urinish uchun blok vaqti oshib boradi
            if t.try_count == 1:
                minutes = 5
            elif t.try_count == 2:
                minutes = 15
            else:
                minutes = 30
                t.state = 'cancelled' # 3-xatodan so'ng tranzaksiya yopiladi
                t.save()

            sender_card.blocked_until = timezone.now() + timedelta(minutes=minutes)
            sender_card.save()

            # Xato haqida ko'p tilli xabarnomalar
            if t.try_count >= 3:
                msg_30 = {
                    'uz': f" (3-xato. Karta {minutes} min bloklandi)",
                    'ru': f" (3-я ошибка. Карта заблокирована на {minutes} мин)",
                    'en': f" (3rd error. Card blocked for {minutes} min)"
                }
                return get_rpc_error(32711, lang=lang, extra_msg=msg_30.get(lang, msg_30['uz']))

            msg_extra = {
                'uz': f"(Xato {t.try_count}/3. {minutes} min blok)",
                'ru': f"(Ошибка {t.try_count}/3. Блок на {minutes} мин)",
                'en': f"(Error {t.try_count}/3. {minutes} min block)"
            }
            return get_rpc_error(32712, lang=lang, extra_msg=msg_extra.get(lang, msg_extra['uz']))

        # --- 4. BALANS VA MUVAFFAQIYATLI O'TKAZMA ---
        if sender_card.balance < t.sending_amount:
            return get_rpc_error(32702, lang=lang)

        # Balanslarni yangilash
        sender_card.balance -= t.sending_amount
        receiver_card.balance += t.sending_amount
        sender_card.save()
        receiver_card.save()

        # Tranzaksiyani tasdiqlash
        t.state = 'confirmed'
        t.confirmed_at = timezone.now()
        t.save()

        # --- 5. CACHE INVALIDATION (Keshni tozalash) ---
        # Balans o'zgargani sababli Redis keshidagi eski ma'lumotlarni o'chirib yuboramiz
        CACHE_PREFIX = "core:v1:card:info"
        cache.delete(f"{CACHE_PREFIX}:{t.sender_card_number}")
        cache.delete(f"{CACHE_PREFIX}:{t.receiver_card_number}")
        
        otp_log.is_used = True
        otp_log.save()

        # --- 6. YAKUNIY JAVOB (ELECTRONIC RECEIPT) ---
        status_txt = {"uz": "Muvaffaqiyatli", "ru": "Успешно", "en": "Success"}.get(lang, "Success")
        
        return Success({
            "ext_id": t.ext_id,
            "details": {
                "status": status_txt,
                "amount": f"{t.sending_amount:,.2f} UZS",
                "date": t.confirmed_at.strftime("%d.%m.%Y %H:%M:%S"),
                "sender": card_mask(t.sender_card_number),
                "sender_name": sender_card.owner.get_full_name() if sender_card.owner else "N/A",
                "receiver": card_mask(t.receiver_card_number),
                "receiver_name": receiver_card.owner.get_full_name() if receiver_card.owner else "N/A"
            }
        })
    






# Ushbu metod mavjud tranzaksiya uchun yangi OTP kodini generatsiya qiladi, 
# eskilarini bekor qiladi va xavfsizlik filtrlaridan o'tkazadi.
@method
@audit_logger
def resend_otp(context, **params):
    """
    Tasdiqlash kodini (OTP) qayta yuborish.

    Mantiq:
    1. Tranzaksiyaning 'created' holatidaligini tekshiradi.
    2. Urinishlar soni 3 tadan oshgan bo'lsa, kod yuborishni taqiqlaydi (Security Block).
    3. Eski faol (is_used=False) OTP kodlarini bekor qiladi.
    4. Yangi 6 xonali kod yaratib, uning SHA-256 xeshini bazada saqlaydi.
    5. Tranzaksiya vaqtini (`created_at`) yangilab, amal qilish muddatini uzaytiradi.
    6. Telegram orqali yangi kodni maskalangan ma'lumotlar bilan yuboradi.

    Args:
        ext_id (str): transfer_create'dan qaytgan unikal ID.
        lang (str): Xabar tili (uz, ru, en).

    Returns:
        Success: Yangi kod yuborilganligi va amal qilish muddati (120s).
    """
    lang = params.get("lang", "uz").lower()
    ext_id = params.get("ext_id")

    # 1. Tranzaksiyani tekshirish (Step 1)
    t = Transfer.objects.filter(ext_id=ext_id, state='created').first()
    if not t:
        return get_rpc_error(32706, lang=lang)

    # --- 2. XAVFSIZLIK: URINISHLAR SONI (Step 2) ---
    # Agar foydalanuvchi allaqachon 3 marta xato qilgan bo'lsa, qayta yuborish bloklanadi.
    if t.try_count >= 3:
        return get_rpc_error(32711, lang=lang)

    # 3. Kartani (sender) topish (Step 3)
    sender = Card.objects.filter(card_number=t.sender_card_number).first()
    if not sender:
        return get_rpc_error(32718, lang=lang)

    # --- 4. YANGI OTP YARATISH VA HASHLASH (Step 4) ---
    new_otp_raw = str(random.randint(100000, 999999))
    otp_hash = hashlib.sha256(new_otp_raw.encode()).hexdigest()

    # Eskilarini "ishlatilgan" deb belgilash (Tozalash)
    OTP.objects.filter(transfer=t, is_used=False).update(is_used=True)

    # Yangi OTP obyektini yaratish
    OTP.objects.create(
        user=sender.owner,
        card=sender,
        transfer=t,
        purpose="Money Transfer",
        otp_hash=otp_hash, 
        expires_at=timezone.now() + timedelta(minutes=2),
        is_used=False
    )

    # Tranzaksiya vaqtini yangilash (Step 5)
    t.created_at = timezone.now()
    t.save()

    # --- 5. KO'P TILLI XABAR VA MASKALASH (Step 6) ---
    name = sender.owner.get_full_name() if sender.owner else "Mijoz"
    # Ismni maskalash (Xavfsizlik standarti)
    name_hidden = f"{name[:2]}***" if len(name) > 2 else name
    s_mask = card_mask(t.sender_card_number)

    resend_msgs = {
        'uz': f"🔄 <b>KODNI QAYTA YUBORISH</b>\n\nKimga: <b>{name_hidden}</b>\nKarta: <b>{s_mask}</b>\nYangi kod: <code>{new_otp_raw}</code>",
        'ru': f"🔄 <b>ПОВТОРНЫЙ КОД</b>\n\nКому: <b>{name_hidden}</b>\nКарта: <b>{s_mask}</b>\nНовый код: <code>{new_otp_raw}</code>",
        'en': f"🔄 <b>RESEND CODE</b>\n\nTo: <b>{name_hidden}</b>\nCard: <b>{s_mask}</b>\nNew code: <code>{new_otp_raw}</code>"
    }

    send_telegram_message(CHAT_ID, TOKEN, resend_msgs.get(lang, resend_msgs['uz']))

    return Success({
        "ext_id": ext_id,
        "otp_sent": True,
        "expires_in": 120
    })



# Ushbu metod tranzaksiyani bekor qiladi. Agar pul o'tkazilgan bo'lsa, 
# 60 soniya ichida uni qaytarib olish (Refund) mantiqini ishga tushiradi.
@method
@audit_logger
def transfer_cancel(context, **params):
    """
    Tranzaksiyani bekor qilish va mablag'ni qaytarish (Reversal).

    Mantiq:
    1. Tranzaksiyani 'select_for_update' orqali qulflaydi.
    2. Agar tranzaksiya allaqachon 'confirmed' bo'lsa, vaqtni tekshiradi (60s limit).
    3. Refund vaqtida qabul qiluvchining balansida yetarli mablag' borligini tekshiradi.
    4. Mablag'ni teskari yo'nalishda qaytaradi (Receiver -> Sender).
    5. Agar tranzaksiya hali 'created' bo'lsa, uni shunchaki bekor qiladi.

    Args:
        ext_id (str): Bekor qilinishi kerak bo'lgan tranzaksiya IDsi.
    
    Returns:
        Success: Bekor qilinganlik holati va tizim xabari.
    """
    lang = params.get("lang", "uz").lower()
    ext_id = params.get("ext_id")
    
    with transaction.atomic():
        # --- 1. TRANZAKSIYANI QIDIRISH VA QULFLASH ---
        t = Transfer.objects.select_for_update().filter(ext_id=ext_id).first()
        
        if not t: 
            return get_rpc_error(32706, lang=lang)
            
        if t.state == 'cancelled': 
            return Success({"ext_id": ext_id, "state": "already_cancelled"})

        # --- 2. VAQT FILTRI (REFUND LIMIT) ---
        # Tasdiqlangan vaqtdan boshlab 60 soniya sanaladi
        start_time = t.confirmed_at if t.confirmed_at else t.created_at
        time_diff = (timezone.now() - start_time).total_seconds()

        # Agar belgilangan vaqt (60s) o'tib ketgan bo'lsa, bekor qilish taqiqlanadi
        if time_diff > 60:
            return get_rpc_error(32713, lang=lang)

        # --- 3. CONFIRMED TRANZAKSIYANI QAYTARISH (REVERSAL) ---
        if t.state == 'confirmed':
            sender_card = Card.objects.select_for_update().filter(card_number=t.sender_card_number).first()
            receiver_card = Card.objects.select_for_update().filter(card_number=t.receiver_card_number).first()

            if not sender_card or not receiver_card:
                return get_rpc_error(32718, lang=lang)

            # Anti-Fraud: Qabul qiluvchi pulni ishlatib yubormaganini tekshirish
            if receiver_card.balance < t.sending_amount:
                return get_rpc_error(32719, lang=lang)

            # Pulni qaytarish operatsiyasi (Teskari o'tkazma)
            receiver_card.balance -= t.sending_amount
            sender_card.balance += t.sending_amount
            
            receiver_card.save()
            sender_card.save()
            
            t.state = 'cancelled'
            t.cancelled_at = timezone.now()
            t.save()
            
            return Success({
                "ext_id": ext_id, 
                "state": "cancelled", 
                "message": "Mablag' muvaffaqiyatli qaytarildi"
            })

        # --- 4. HALI TASDIQLANMAGAN TRANZAKSIYANI BEKOR QILISH ---
        t.state = 'cancelled'
        t.cancelled_at = timezone.now()
        t.save()
        
        return Success({"ext_id": ext_id, "state": "cancelled"})
    




# Ushbu metod karta balansini tekshiradi va karta raqami prefiksiga qarab 
# uning qaysi to'lov tizimiga tegishli ekanligini aniqlaydi.
@method
def check_balance(context, **params):
    """
    Karta balansini tekshirish va karta turini aniqlash.

    Mantiq:
    1. Karta raqami va amal qilish muddati bo'yicha bazadan qidiradi.
    2. Topilmasa, 32704 xato kodini (Invalid card/expiry) qaytaradi.
    3. Karta raqamining boshlang'ich raqamlari orqali brendni aniqlaydi:
       - 9860 -> HUMO
       - 8600, 5614, 6262, 5445 -> UZCARD
       - 4... -> VISA
       - 51-55... -> MASTERCARD
    4. Foydalanuvchi tanlagan tilda balans haqida matnli xabar shakllantiradi.

    Args:
        card_number (str): 16 xonali karta raqami.
        card_expire (str): Karta muddati (MMYY).
        lang (str): Til kodi (uz, ru, en).

    Returns:
        Success: Karta egasi, turi, balansi va maskalangan karta raqami.
    """
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    card_expire = params.get("card_expire")
    
    # 1. KARTANI VALIDATSIYA QILISH
    card = Card.objects.filter(card_number=card_number, expire=card_expire).first()
    if not card: 
        return get_rpc_error(32704, lang=lang)

    # --- 2. KARTA TURINI ANIQLASH (BIN Analysis) ---
    c_str = str(card_number)
    card_type = "UNKNOWN"
    
    # Humo to'lov tizimi (Milliy)
    if c_str.startswith('9860'): 
        card_type = "HUMO"
    # Uzcard to'lov tizimi (Milliy va Kobeydjing)
    elif c_str.startswith(('8600', '5614', '6262', '5445')): 
        card_type = "UZCARD"
    # Visa (Xalqaro)
    elif c_str.startswith('4'): 
        card_type = "VISA"
    # MasterCard (Xalqaro)
    elif c_str.startswith(('51', '52', '53', '54', '55')):
        card_type = "MASTERCARD"

    # 3. MA'LUMOTLARNI TAYYORLASH
    owner_masked = (card.owner.get_full_name())
    
    # Ko'p tilli balans xabari
    bal_msgs = {
        'uz': f"Balans: {card.balance:,.2f} UZS",
        'ru': f"Баланс: {card.balance:,.2f} UZS",
        'en': f"Balance: {card.balance:,.2f} UZS"
    }

    return Success({
        "owner": owner_masked,
        "card": card_mask(card_number), # Masalan: 860012****9012
        "card_type": card_type, 
        "balance": float(card.balance), 
        "card_expire": card.expire,
        "message": bal_msgs.get(lang, bal_msgs['uz'])
    })





# Ushbu metod kartani bloklash so'rovini qayta ishlaydi va 
# xavfsizlik uchun SHA-256 xeshlangan OTP yaratadi.
@method
@audit_logger
def card_block_request(context, **params):
    """
    Kartani bloklash uchun OTP so'rovini yaratish.

    Mantiq:
    1. Karta raqami bo'yicha bazadan qidiradi va 'deleted' emasligini tekshiradi.
    2. Karta holati 'active' bo'lmasa, bloklash so'rovini rad etadi.
    3. 6 xonali tasdiqlash kodini generatsiya qiladi.
    4. Kodni SHA-256 orqali xeshlab, OTP modeliga 'BLOCK' maqsadi bilan saqlaydi.
    5. Ochiq kodni Telegram orqali foydalanuvchiga yuboradi.

    Args:
        card_number (str): Bloklanishi kerak bo'lgan 16 xonali karta raqami.
        lang (str): Xabar tili (uz, ru, en).

    Returns:
        Success: OTP yuborilganligi haqida tasdiq xabari.
    """
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    
    # 1. KARTANI TEKSHIRISH
    card = Card.objects.filter(card_number=card_number).first()
    if not card: 
        return get_rpc_error(32718, lang=lang)
    
    # O'chirilgan kartalarni bloklab bo'lmaydi
    if str(card.status).strip() == 'deleted':
        return get_rpc_error(32718, lang=lang)

    # Faqat faol kartalarni bloklash so'rovi qabul qilinadi
    if card.status != 'active':
        error_msgs = {
            'uz': "Karta faol emas.",
            'ru': "Карта не активна.",
            'en': "Card not active."
        }
        return get_rpc_error(32703, lang=lang, extra_msg=error_msgs.get(lang))

    full_name = card.owner.get_full_name() if card.owner else "Mijoz"
    c_mask = card_mask(card_number)
    
    # --- 2. OTP GENERATSIYA VA XAVFSIZLIK ---
    # Ochiq kod (Plain text) faqat xabarnoma uchun
    otp_raw = str(random.randint(100000, 999999))
    
    # Bazaga saqlash uchun SHA-256 xeshi yaratiladi
    otp_hash_value = hashlib.sha256(otp_raw.encode()).hexdigest()
    
    # 3. OTP OBYEKTINI YARATISH (Purpose: BLOCK)
    OTP.objects.create(
        user=card.owner, 
        card=card, 
        purpose=OTP.Purpose.BLOCK, 
        otp_hash=otp_hash_value,
        expires_at=timezone.now() + timedelta(minutes=2),
        is_used=False
    )

    # 4. TELEGRAM XABARNOMASI (Step 4)
    tg_msgs = {
        'uz': f"🛡 <b>KARTANI BLOKLASH</b>\n\nHurmatli <b>{full_name}</b>,\nKarta: <b>{c_mask}</b>\nKod: <code>{otp_raw}</code>",
        'ru': f"🛡 <b>БЛОКИРОВКА КАРТЫ</b>\n\nУважаемый(-ая) <b>{full_name}</b>,\nКарта: <b>{c_mask}</b>\nКод: <code>{otp_raw}</code>",
        'en': f"🛡 <b>BLOCK CARD</b>\n\nDear <b>{full_name}</b>,\nCard: <b>{c_mask}</b>\nCode: <code>{otp_raw}</code>"
    }
    send_telegram_message(CHAT_ID, TOKEN, tg_msgs.get(lang, tg_msgs['uz']))

    return Success({"status": "otp_sent", "message": "OTP yuborildi"})







# Ushbu metod OTP tasdiqlanganidan so'ng kartani uzoq muddatli blok holatiga o'tkazadi.
@method
@audit_logger
def card_block_confirm(context, **params):
    """
    Kartani bloklashni OTP orqali tasdiqlash.

    Mantiq:
    1. Karta raqami bo'yicha bazadan qidiradi.
    2. 'Card Block' maqsadi bilan yaratilgan oxirgi ishlatilmagan OTPni topadi.
    3. OTP kodini xesh orqali tekshiradi (verify_otp).
    4. Karta statusini 'blocked'ga o'zgartiradi.
    5. 'blocked_until' maydonini 100 yil kelajakka suradi (Admin panelda qizil chiroq yonishi uchun).
    6. OTPni ishlatilgan deb belgilaydi va foydalanuvchiga tasdiq xabarini qaytaradi.

    Args:
        card_number (str): 16 xonali karta raqami.
        otp (str): Foydalanuvchi kiritgan 6 xonali kod.
        lang (str): Til kodi (uz, ru, en).

    Returns:
        Success: Bloklash muvaffaqiyatli yakunlangani haqida xabar.
    """
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    otp = params.get("otp")

    # 1. KARTANI TEKSHIRISH
    card = Card.objects.filter(card_number=card_number).first()
    if not card: 
        return get_rpc_error(32718, lang=lang)

    # 2. OTP LOGINI QIDIRISH (Maqsadi faqat 'Card Block' bo'lishi shart)
    otp_log = OTP.objects.filter(card=card, purpose="Card Block", is_used=False).last()

    # OTP mavjudligi va to'g'riligini tekshirish
    if not otp_log or not otp_log.verify_otp(otp):
        return get_rpc_error(32712, lang=lang)

    # --- 3. STATUS VA VIZUAL INDIKATORLARNI O'ZGARTIRISH ---
    # Asosiy statusni o'zgartiramiz
    card.status = 'blocked'
    
    # Admin paneldagi 'check_block_status' mantiqi 'blocked_until'ga tayanadi.
    # Vizual indikator (chiroq) qizil bo'lishi uchun muddatni 100 yilga belgilaymiz.
    card.blocked_until = timezone.now() + timezone.timedelta(days=365*100)
    
    card.save() 
    # ----------------------------------------------

    # 4. OTPNI YOPISH
    otp_log.is_used = True
    otp_log.save()

    # 5. JAVOB XABARINI TAYYORLASH
    full_name = card.owner.get_full_name() if card.owner else "Mijoz"
    c_mask = card_mask(card_number)
    
    response_msgs = {
        'uz': f"Hurmatli {full_name}, {c_mask} kartangiz bloklandi.",
        'ru': f"Уважаемый(-ая) {full_name}, ваша карта {c_mask} заблокирована.",
        'en': f"Dear {full_name}, your card {c_mask} has been blocked."
    }

    return Success({
        "status": "success",
        "message": response_msgs.get(lang, response_msgs['uz'])
    })




# Ushbu metod kartani bazadan o'chirish (soft delete) so'rovini yaratadi 
# va tasdiqlash uchun xeshlangan OTP kodini generatsiya qiladi.
@method
def card_delete_request(context, **params):
    """
    Kartani o'chirish uchun OTP so'rovini yaratish.

    Mantiq:
    1. Karta raqami bo'yicha bazadan qidiradi.
    2. Karta allaqachon 'deleted' holatida bo'lsa, so'rovni rad etadi.
    3. 6 xonali tasdiqlash kodini yaratadi (Plain text).
    4. Xavfsizlik uchun kodni SHA-256 orqali xeshlab bazaga saqlaydi (otp_hash).
    5. Avvalgi barcha faol 'DELETE' maqsadli OTP kodlarini bekor qiladi (cleanup).
    6. Ochiq kodni Telegram orqali ko'p tilli xabarnoma ko'rinishida yuboradi.

    Args:
        card_number (str): O'chirilishi kerak bo'lgan karta raqami.
        lang (str): Xabar tili (uz, ru, en).

    Returns:
        Success: OTP yuborilganligi haqida xabar.
    """
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    
    # --- 1. KARTANI VALIDATSIYA QILISH ---
    card = Card.objects.filter(card_number=card_number).first()
    if not card: 
        return get_rpc_error(32718, lang=lang)
    
    # 2. HOLATNI TEKSHIRISH (Duplicate request protection)
    if hasattr(card, 'status') and card.status == 'deleted':
        error_msgs = {
            'uz': "Bu karta allaqachon o'chirilgan.",
            'ru': "Эта карта уже удалена.",
            'en': "This card is already deleted."
        }
        return get_rpc_error(32703, lang=lang, extra_msg=error_msgs.get(lang))

    # --- 3. OTP GENERATSIYA VA XAVFSIZLIK ---
    # Ochiq kod faqat xabar yuborish uchun (Plain text)
    otp_raw = str(random.randint(100000, 999999))
    full_name = card.owner.get_full_name() if card.owner else "Mijoz"
    c_mask = card_mask(card_number)

    # Bazada saqlash uchun SHA-256 xeshi yaratiladi
    otp_hash_value = hashlib.sha256(otp_raw.encode()).hexdigest()

    # 4. ESKI OTP LARNI TOZALASH
    # Bitta karta uchun bir vaqtda faqat bitta o'chirish kodi faol bo'lishi kerak
    OTP.objects.filter(card=card, purpose=OTP.Purpose.DELETE, is_used=False).update(is_used=True)

    # 5. YANGI OTP LOGINI SAQLASH
    OTP.objects.create(
        user=card.owner, 
        card=card, 
        purpose=OTP.Purpose.DELETE,
        otp_hash=otp_hash_value,
        expires_at=timezone.now() + timedelta(minutes=2),
        is_used=False
    )

    # --- 6. TELEGRAM XABARNOMASI ---
    tg_msgs = {
        'uz': f"⚠️ <b>KARTANI O'CHIRISH</b>\n\nHurmatli <b>{full_name}</b>,\nKarta: <b>{c_mask}</b>\nKod: <code>{otp_raw}</code>",
        'ru': f"⚠️ <b>УДАЛЕНИЕ КАРТЫ</b>\n\nУважаемый(-ая) <b>{full_name}</b>,\nКарта: <b>{c_mask}</b>\nКод: <code>{otp_raw}</code>",
        'en': f"⚠️ <b>DELETE CARD</b>\n\nDear <b>{full_name}</b>,\nCard: <b>{c_mask}</b>\nCode: <code>{otp_raw}</code>"
    }
    
    send_telegram_message(CHAT_ID, TOKEN, tg_msgs.get(lang, tg_msgs['uz']))

    return Success({
        "status": "otp_sent", 
        "message": "Karta o'chirilishini tasdiqlash uchun OTP yuborildi"
    })






# Ushbu metod OTP tasdiqlanganidan so'ng kartani 'deleted' holatiga o'tkazadi (Soft Delete).
@method
@audit_logger
@transaction.atomic
def card_delete_confirm(context, **params):
    """
    Kartani o'chirishni OTP orqali tasdiqlash.

    Mantiq:
    1. Bazadan hali o'chirilmagan (exclude status='deleted') kartani qidiradi.
    2. 'DELETE' maqsadli (purpose) oxirgi faol OTPni topadi.
    3. OTP kodini xesh (SHA-256) orqali tekshiradi (verify_otp).
    4. Kartani haqiqatda o'chirmasdan, statusini 'deleted'ga o'zgartiradi (Soft Delete).
    5. Tranzaksion yaxlitlikni ta'minlash uchun @transaction.atomic ishlatiladi.

    Args:
        card_number (str): 16 xonali karta raqami.
        otp (str): Foydalanuvchi kiritgan 6 xonali kod.
        lang (str): Til kodi (uz, ru, en).

    Returns:
        Success: Karta o'chirilganligi haqida yakuniy xabar.
    """
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    otp = params.get("otp")

    # --- 1. KARTANI QIDIRISH ---
    # Allaqachon o'chirilgan kartalarni qayta o'chirmaslik uchun 'exclude' ishlatamiz
    card = Card.objects.filter(card_number=card_number).exclude(status='deleted').first()
    if not card: 
        return get_rpc_error(32718, lang=lang)

    # --- 2. OTP TASDIQLASH (Context Isolation) ---
    # Faqat 'DELETE' maqsadi bilan yuborilgan kod qabul qilinadi
    otp_log = OTP.objects.filter(
        card=card, 
        purpose=OTP.Purpose.DELETE, 
        is_used=False
    ).last()
    
    if not otp_log or not otp_log.verify_otp(otp):
        # Noto'g'ri yoki muddati o'tgan OTP
        return get_rpc_error(32712, lang=lang)

    # --- 3. SOFT DELETE OPERATSIYASI ---
    # Fintech standartlariga ko'ra, ma'lumotlar fizik o'chirilmaydi
    card.status = 'deleted'
    card.save()

    # OTPni yopish
    otp_log.is_used = True
    otp_log.save()

    # 4. JAVOBNI TAYYORLASH
    full_name = card.owner.get_full_name() if card.owner else "Mijoz"
    c_mask = card_mask(card_number)

    response_msgs = {
        'uz': f"Hurmatli {full_name}, {c_mask} kartangiz muvaffaqiyatli o'chirildi.",
        'ru': f"Уважаемый(-ая) {full_name}, карта {c_mask} удалена.",
        'en': f"Dear {full_name}, your card {c_mask} has been deleted."
    }

    return Success({
        "status": "deleted",
        "message": response_msgs.get(lang, response_msgs['uz'])
    })