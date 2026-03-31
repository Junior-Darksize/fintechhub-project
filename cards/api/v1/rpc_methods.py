import hashlib
import random
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone
from django.db import transaction
from jsonrpcserver import method, Success
from cards.models import User, OTP, Card, Transfer
from cards.utils import (
    get_rpc_error, send_telegram_message, card_mask, 
    phone_mask, is_luhn_valid, get_live_exchange_rate, mask_name
)

# Telegram Bot sozlamalari
TG_TOKEN = "8448513005:AAFCmG5C9a2_3Tbh_bDzoXThUfotsTUlx0E"
TG_CHAT_ID = 1078739901

# --- 1. USER LOGIN ---
@method
def user_login(context, **params):
    lang = params.get("lang", "uz").lower()
    first_name = params.get("first_name", "").strip()
    last_name = params.get("last_name", "").strip()
    phone_raw = params.get("phone")

    if not first_name or not last_name or not phone_raw:
        return get_rpc_error(32722, lang=lang)

    phone = str(phone_raw).replace("+", "")
    user = User.objects.filter(
        phone_number__icontains=phone,
        first_name__iexact=first_name,
        last_name__iexact=last_name
    ).first()

    if not user:
        return get_rpc_error(32722, lang=lang)

    if user.blocked_until and timezone.now() < user.blocked_until:
        rem = int((user.blocked_until - timezone.now()).total_seconds())
        return get_rpc_error(32725, lang=lang, extra_msg=f"{rem // 60:02d}:{rem % 60:02d}")

    # --- OTP YARATISH VA HASHLASH (METOD ICHIDA) ---
    raw_code = str(random.randint(100000, 999999))
    otp_hash = hashlib.sha256(raw_code.encode()).hexdigest()
    
    OTP.objects.create(
        user=user,
        purpose="User Login",
        otp_hash=otp_hash,
        expires_at=timezone.now() + timedelta(minutes=2),
        is_used=False
    )
    # ----------------------------------------------
    
    msg = f"🔐 <b>Kirish kodi</b>\nFoydalanuvchi: {user.get_full_name()}\nKod: <code>{raw_code}</code>"
    send_telegram_message(TG_CHAT_ID, TG_TOKEN, msg)

    return Success({"status": "otp_sent", "phone": phone_mask(user.phone_number)})



@method
def user_login_confirm(context, **params):
    lang = params.get("lang", "uz").lower()
    phone_raw = params.get("phone")
    otp_input = params.get("otp")

    phone = str(phone_raw).replace("+", "")
    user = User.objects.filter(phone_number__icontains=phone).first()
    if not user: return get_rpc_error(32722, lang=lang)

    if user.blocked_until and timezone.now() < user.blocked_until:
        rem = int((user.blocked_until - timezone.now()).total_seconds())
        return get_rpc_error(32725, lang=lang, extra_msg=f"{rem // 60:02d}:{rem % 60:02d}")

    otp_obj = OTP.objects.filter(user=user, purpose="User Login", is_used=False).last()
    if not otp_obj: return get_rpc_error(32710, lang=lang)

    # verify_otp modeli ichida inputni hashlangan variant bilan solishtiradi
    if otp_obj.verify_otp(otp_input):
        user.blocked_until = None
        user.save()
        return Success({
            "status": "success",
            "data": {"full_name": user.get_full_name(), "phone": phone_mask(user.phone_number)}
        })
    else:
        otp_obj.refresh_from_db()
        if otp_obj.try_count >= 3:
            user.blocked_until = timezone.now() + timedelta(minutes=1)
            user.save()
            return get_rpc_error(32724, lang=lang)
        
        return get_rpc_error(32712, lang=lang, extra_msg=f" (Urinishlar: {otp_obj.try_count}/3)")



# --- 3. RESEND LOGIN ---
@method
def resend_otp_login(context, **params):
    lang = params.get("lang", "uz").lower()
    phone_raw = params.get("phone")
    phone = str(phone_raw).replace("+", "")
    user = User.objects.filter(phone_number__icontains=phone).first()

    if not user: 
        return get_rpc_error(32722, lang=lang)

    # 1. Eski (ishlatilmagan) OTP kodeslarini bekor qilish
    OTP.objects.filter(user=user, purpose="User Login", is_used=False).update(is_used=True)

    # 2. YANGI OTP YARATISH VA HASHLASH (METOD ICHIDA)
    raw_code = str(random.randint(100000, 999999))
    otp_hash = hashlib.sha256(raw_code.encode()).hexdigest()
    
    OTP.objects.create(
        user=user,
        purpose="User Login",
        otp_hash=otp_hash,
        expires_at=timezone.now() + timedelta(minutes=2),
        is_used=False
    )
    
    # 3. Telegramga yuborish
    send_telegram_message(TG_CHAT_ID, TG_TOKEN, f"🔄 Yangi kod: <code>{raw_code}</code>")

    return Success({"status": "otp_resent"})


# --- 2. CARD ADD (Karta Bog'lash) ---
@method
def card_add_request(context, **params):
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    phone_raw = params.get("phone")

    # Kiruvchi telefon raqamini formatlash
    phone = str(phone_raw).replace("+", "").strip()
    
    # 1. Karta va foydalanuvchini qidirish
    card = Card.objects.filter(card_number=card_number).first()
    # Sizda User modelida 'phone_number' maydoni bor ekan:
    user = User.objects.filter(phone_number__icontains=phone).first()

    # 2. Dastlabki tekshiruvlar
    if not card:
        return get_rpc_error(32704, lang=lang) # Karta topilmadi
    
    if not user:
        return get_rpc_error(32717, lang=lang) # Foydalanuvchi topilmadi (Xato tel)

    # --- TELEFON RAQAMINI TEKSHIRISH ---
    # User modelidagi phone_number ni yuborilgan raqam bilan solishtiramiz
    db_user_phone = str(user.phone_number).replace("+", "").strip()
    
    if db_user_phone != phone:
        # 32721 - "Noto'g'ri telefon raqami"
        return get_rpc_error(32721, lang=lang) 
    # -----------------------------------

    # 3. Karta holatini tekshirish
    if card.is_sms_enabled:
        if card.owner == user:
            # Agar SMS yoqilgan bo'lsa, OTP yubormasdan to'xtatish
            msgs = {
                'uz': "Karta allaqachon ulangan.",
                'ru': "Карта уже привязаna.",
                'en': "Card already bound."
            }
            return Success({"status": "already_bound", "message": msgs.get(lang, msgs['uz'])})
        
        if card.owner and card.owner != user:
            return get_rpc_error(32705, lang=lang)

    # 4. Statusni tekshirish
    if str(card.status).strip() != 'active':
        return get_rpc_error(32706, lang=lang)

    # 5. Tilni saqlash va OTP yuborish qismi (Sizning kodingiz davomi...)
    user.lang = lang
    user.save()

    # 5. OTP YARATISH VA HASHLASH
    raw_code = str(random.randint(100000, 999999))
    otp_hash = hashlib.sha256(raw_code.encode()).hexdigest()
    
    # Eskilarini tozalash
    OTP.objects.filter(user=user, card=card, purpose="Card Binding", is_used=False).delete()
    
    OTP.objects.create(
        user=user,
        card=card,
        purpose="Card Binding",
        otp_hash=otp_hash,
        expires_at=timezone.now() + timedelta(minutes=2),
        is_used=False
    )
    
    # 6. Telegram xabari
    otp_msgs = {
        'uz': f"💳 <b>KARTANI ULASH</b>\n\nKarta: <code>{card_mask(card_number)}</code>\nTasdiqlash kodi: <code>{raw_code}</code>",
        'ru': f"💳 <b>ПРИВЯЗКА КАРТЫ</b>\n\nКарта: <code>{card_mask(card_number)}</code>\nКод подтверждения: <code>{raw_code}</code>",
        'en': f"💳 <b>CARD BINDING</b>\n\nCard: <code>{card_mask(card_number)}</code>\nConfirmation code: <code>{raw_code}</code>"
    }
    
    send_telegram_message(TG_CHAT_ID, TG_TOKEN, otp_msgs.get(lang, otp_msgs['uz']))

    return Success({
        "status": "otp_sent", 
        "card_number": card_mask(card_number),
        "expires_in": 120
    })


@method
def card_add_confirm(context, **params):
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    otp_input = params.get("otp")

    card = Card.objects.filter(card_number=card_number).first()
    if not card: 
        return get_rpc_error(32718, lang=lang)

    # Oxirgi faol OTPni olish
    otp_obj = OTP.objects.filter(card=card, purpose="Card Binding", is_used=False).last()
    
    if not otp_obj or not otp_obj.verify_otp(otp_input):
        return get_rpc_error(32712, lang=lang)

    # Karta SMS xizmatini yoqamiz
    card.is_sms_enabled = True
    card.save()

    # Karta turini aniqlash (BIN orqali)
    c_str = str(card_number)
    card_type = "UNKNOWN"
    # Humo: 9860
    if c_str.startswith('9860'): 
        card_type = "HUMO"
    # Uzcard: 8600, 5614, 6262, 5445
    elif c_str.startswith(('8600', '5614', '6262', '5445')): 
        card_type = "UZCARD"
    # Visa: 4
    elif c_str.startswith('4'): 
        card_type = "VISA"
    # MasterCard: 51, 52, 53, 54, 55 (5614 dan tashqari)
    elif c_str.startswith(('51', '52', '53', '54', '55')):
        card_type = "MASTERCARD"

    return Success({
        "status": "card_added",
        "data": {
            "card_number": card_mask(card_number),
            "card_type": card_type, # Yangi qo'shilgan maydon
            "card_expire": card.expire,
            "owner_name": mask_name(card.owner.get_full_name()),
            "balance": float(card.balance),
            "is_sms_enabled": card.is_sms_enabled
        }
    })






@method
def card_check(context, **params):
    lang = params.get("lang", "uz").lower()
    r_card_num = params.get("receiver_card_number")

    # 1. Luhn algoritmi bo'yicha tekshirish
    if not is_luhn_valid(r_card_num):
        return get_rpc_error(32718, lang=lang)

    # 2. Kartani bazadan qidirish
    receiver = Card.objects.filter(card_number=r_card_num).first()

    if not receiver:
        return get_rpc_error(32718, lang=lang)

    # 3. Karta holatini tekshirish
    if receiver.status != 'active':
        return get_rpc_error(32705, lang=lang)

    # --- KARTA TURINI ANIQLASH ---
    c_str = str(r_card_num)
    card_type = "UNKNOWN"
    
    # Humo: 9860
    if c_str.startswith('9860'): 
        card_type = "HUMO"
    # Uzcard: 8600, 5614, 6262, 5445
    elif c_str.startswith(('8600', '5614', '6262', '5445')): 
        card_type = "UZCARD"
    # Visa: 4
    elif c_str.startswith('4'): 
        card_type = "VISA"
    # MasterCard: 51, 52, 53, 54, 55 (5614 Uzcard bo'lgani uchun elif tartibi muhim)
    elif c_str.startswith(('51', '52', '53', '54', '55')):
        card_type = "MASTERCARD"
    # ----------------------------

    # 4. Karta egasining ism-familiyasini olish
    if receiver.owner:
        first_name = receiver.owner.first_name
        last_name = receiver.owner.last_name
        # Xavfsizlik uchun ismni niqoblash: "JAMOLIDDIN S****"
        masked_name = f"{first_name.title()} {last_name[0].title()}****"
    else:
        masked_name = "INCOGNITO"

    return Success({
        "receiver_name": masked_name,
        "card_type": card_type,
        "status": "verified"
    })





# Telegram sozlamalari
TOKEN = "8448513005:AAFCmG5C9a2_3Tbh_bDzoXThUfotsTUlx0E"
CHAT_ID = 1078739901

@method
def transfer_create(context, **params):
    # 1. Parametrlarni olish
    lang = params.get("lang", "uz").lower()
    ext_id = params.get("ext_id")
    s_card_num = params.get("sender_card_number")
    s_card_expiry = params.get("sender_card_expiry")
    r_card_num = params.get("receiver_card_number")
    raw_amount = Decimal(str(params.get("sending_amount", 0)))
    currency = params.get("currency", "UZS").upper()

    # 2. Dastlabki tekshiruvlar (Valyuta va Luhn)
    allowed_currencies = ['UZS', 'RUB', 'USD']
    if currency not in allowed_currencies:
        return get_rpc_error(32707, lang=lang)

    if not is_luhn_valid(s_card_num) or not is_luhn_valid(r_card_num):
        return get_rpc_error(32718, lang=lang)

    # 3. Kartalarni bazadan qidirish
    sender = Card.objects.filter(card_number=s_card_num).first()
    receiver = Card.objects.filter(card_number=r_card_num).first()

    if not sender or not receiver:
        return get_rpc_error(32718, lang=lang)

    # 4. Karta ma'lumotlarini tekshirish
    if sender.expire != s_card_expiry:
        return get_rpc_error(32704, lang=lang)

    if sender.status != 'active' or receiver.status != 'active':
        return get_rpc_error(32705, lang=lang)

    if not sender.owner or not sender.owner.phone_number:
        return get_rpc_error(32720, lang=lang)

    if not sender.is_sms_enabled:
        return get_rpc_error(32703, lang=lang)

    # 5. Blokirovka holatini tekshirish
    if sender.blocked_until and timezone.now() < sender.blocked_until:
        rem = int((sender.blocked_until - timezone.now()).total_seconds())
        return get_rpc_error(32716, lang=lang, extra_msg=f"({rem // 60:02d}:{rem % 60:02d})")

    # 6. Balansni tekshirish (Kursga o'girgan holda)
    rate = get_live_exchange_rate(currency)
    total_in_uzs = (raw_amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if sender.balance < total_in_uzs:
        return get_rpc_error(32702, lang=lang)

    # 7. ESKI TRANZAKSIYALARNI BEKOR QILISH
    Transfer.objects.filter(
        sender_card_number=s_card_num, 
        state='created'
    ).update(state='cancelled', updated_at=timezone.now())

    # 8. Yangi Transfer obyektini yaratish
    transfer = Transfer.objects.create(
        ext_id=ext_id,
        sender_card_number=s_card_num,
        receiver_card_number=r_card_num,
        sender_card_expiry=s_card_expiry,
        sending_amount=total_in_uzs,
        currency=currency
    )
    
    # --- OTP YARATISH VA HASHLASH (METOD ICHIDA) ---
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
    # ----------------------------------------------

    # 9. KO'P TILLI TELEGRAM OTP XABARI
    name = sender.owner.get_full_name() if sender.owner else "Mijoz"
    name_hidden = mask_name(name) # "J**** S****" kabi
    amt_f = f"{raw_amount:,.2f} {currency}"
    s_mask = card_mask(s_card_num)

    otp_msgs = {
        'uz': (
            f"💸 <b>TASDIQLASH KODI</b>\n\n"
            f"Maqsad: <b>Pul o'tkazmasi</b>\n"
            f"Kimdan: <b>{name_hidden}</b>\n"
            f"Karta: <b>{s_mask}</b>\n"
            f"Miqdor: <b>{amt_f}</b>\n\n"
            f"Kod: <code>{otp_code}</code>"
        ),
        'ru': (
            f"💸 <b>КОД ПОДТВЕРЖДЕНИЯ</b>\n\n"
            f"Цель: <b>Перевод средств</b>\n"
            f"От кого: <b>{name_hidden}</b>\n"
            f"Карта: <b>{s_mask}</b>\n"
            f"Сумма: <b>{amt_f}</b>\n\n"
            f"Код: <code>{otp_code}</code>"
        ),
        'en': (
            f"💸 <b>CONFIRMATION CODE</b>\n\n"
            f"Purpose: <b>Money transfer</b>\n"
            f"From: <b>{name_hidden}</b>\n"
            f"Card: <b>{s_mask}</b>\n"
            f"Amount: <b>{amt_f}</b>\n\n"
            f"Code: <code>{otp_code}</code>"
        )
    }

    # Telegramga yuborish (lang bo'yicha, topilmasa 'uz')
    send_telegram_message(TG_CHAT_ID, TG_TOKEN, otp_msgs.get(lang, otp_msgs['uz']))

    return Success({
        "ext_id": ext_id,
        "state": "created",
        "otp_sent": True,
        "expires_in": 120
    })

@method
def transfer_confirm(context, **params):
    lang = params.get("lang", "uz").lower()
    ext_id = params.get("ext_id")
    otp_input = params.get("otp")

    with transaction.atomic():
        # 1. Tranzaksiyani qulflash
        t = Transfer.objects.select_for_update().filter(ext_id=ext_id, state='created').first()
        if not t:
            return get_rpc_error(32706, lang=lang)

        sender_card = Card.objects.select_for_update().filter(card_number=t.sender_card_number).first()
        receiver_card = Card.objects.select_for_update().filter(card_number=t.receiver_card_number).first()

        # --- BLOKNI TEKSHIRISH ---
        if sender_card.blocked_until and timezone.now() < sender_card.blocked_until:
            rem = int((sender_card.blocked_until - timezone.now()).total_seconds())
            return get_rpc_error(32716, lang=lang, extra_msg=f"({rem // 60:02d}:{rem % 60:02d})")

        # 2. OTP topish
        otp_log = OTP.objects.filter(transfer=t, is_used=False).last()
        if not otp_log:
            return get_rpc_error(32710, lang=lang)

        # 3. Vaqt va OTP tekshirish
        time_passed = (timezone.now() - otp_log.created_at).total_seconds()
        is_otp_correct = otp_log.verify_otp(otp_input)

        if time_passed > 120 or not is_otp_correct:
            t.try_count += 1
            t.save()
            
            # Progressiv bloklash mantiqi
            if t.try_count == 1:
                minutes = 5
            elif t.try_count == 2:
                minutes = 15
            else:
                minutes = 30
                t.state = 'cancelled'
                t.save()

            sender_card.blocked_until = timezone.now() + timedelta(minutes=minutes)
            sender_card.save()

            # --- KO'P TILLI XATOLIK XABARLARI ---
            if t.try_count >= 3:
                msg_30 = {
                    'uz': f" (3-xato. Karta {minutes} min bloklandi)",
                    'ru': f" (3-я ошибка. Карта заблокирована на {minutes} мин)",
                    'en': f" (3rd error. Card blocked for {minutes} min)"
                }
                return get_rpc_error(32711, lang=lang, extra_msg=msg_30.get(lang, msg_30['uz']))

            # 1 va 2-urinishlar uchun xabarlar
            msg_extra = {
                'uz': f"(Xato {t.try_count}/3. {minutes} min blok)",
                'ru': f"(Ошибка {t.try_count}/3. Блок на {minutes} мин)",
                'en': f"(Error {t.try_count}/3. {minutes} min block)"
            }
            return get_rpc_error(32712, lang=lang, extra_msg=msg_extra.get(lang, msg_extra['uz']))

        # 4. Balans tekshirish
        if sender_card.balance < t.sending_amount:
            return get_rpc_error(32702, lang=lang)

        # 5. Muvaffaqiyatli o'tkazma
        sender_card.balance -= t.sending_amount
        receiver_card.balance += t.sending_amount
        sender_card.save()
        receiver_card.save()

        t.state = 'confirmed'
        t.confirmed_at = timezone.now()
        t.save()
        
        otp_log.is_used = True
        otp_log.save()

        # 6. JSON-RPC Muvaffaqiyatli javob (Chek)
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



@method
def resend_otp(context, **params):
    lang = params.get("lang", "uz").lower()
    ext_id = params.get("ext_id")

    # 1. Tranzaksiyani tekshirish
    t = Transfer.objects.filter(ext_id=ext_id, state='created').first()
    if not t:
        return get_rpc_error(32706, lang=lang)

    # 2. Urinishlar soni (Bloklangan bo'lsa qayta yubormaymiz)
    if t.try_count >= 3:
        return get_rpc_error(32711, lang=lang)

    # 3. Kartani (sender) topish
    sender = Card.objects.filter(card_number=t.sender_card_number).first()
    if not sender:
        return get_rpc_error(32718, lang=lang)

    # 4. Yangi OTP yaratish va Hashlash
    new_otp_raw = str(random.randint(100000, 999999))
    # Hashlash (Sizda hashlib ishlatilgan edi)
    otp_hash = hashlib.sha256(new_otp_raw.encode()).hexdigest()

    # Eskilarini "ishlatilgan" yoki "eskirgan" qilib belgilash (ixtiyoriy, lekin tartib uchun yaxshi)
    OTP.objects.filter(transfer=t, is_used=False).update(is_used=True)

    # Yangi OTP logini yaratish
    OTP.objects.create(
        user=sender.owner,
        card=sender,
        transfer=t,
        purpose="Money Transfer",
        otp_hash=otp_hash, # 'set_otp' o'rniga to'g'ridan-to'g'ri hashni saqlaymiz
        expires_at=timezone.now() + timedelta(minutes=2),
        is_used=False
    )

    # Tranzaksiya vaqtini yangilash (kod muddati yangilanishi uchun)
    t.created_at = timezone.now()
    t.save()

    # 5. Telegram xabari
    name = sender.owner.get_full_name() if sender.owner else "Mijoz"
    # Ismni maskalash (xavfsizlik uchun)
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


@method
def transfer_cancel(context, **params):
    lang = params.get("lang", "uz").lower()
    ext_id = params.get("ext_id")
    
    with transaction.atomic():
        # Tranzaksiyani bazadan qidiramiz va lock (select_for_update) qilamiz
        t = Transfer.objects.select_for_update().filter(ext_id=ext_id).first()
        
        if not t: 
            return get_rpc_error(32706, lang=lang) # Tranzaksiya topilmadi
            
        if t.state == 'cancelled': 
            return Success({"ext_id": ext_id, "state": "already_cancelled"})

        # --- VAQTNI TEKSHIRISH ---
        # confirmed_at bo'lmasa created_at olinadi
        start_time = t.confirmed_at if t.confirmed_at else t.created_at
        time_diff = (timezone.now() - start_time).total_seconds()

        # Agar 60 soniyadan ko'p vaqt o'tgan bo'lsa, bekor qilib bo'lmaydi
        if time_diff > 60:
            return get_rpc_error(32713, lang=lang) # "Метод не разрешён"

        # --- CONFIRMED HOLATIDAGI TRANZAKSIYANI BEKOR QILISH (PULNI QAYTARISH) ---
        if t.state == 'confirmed':
            sender_card = Card.objects.select_for_update().filter(card_number=t.sender_card_number).first()
            receiver_card = Card.objects.select_for_update().filter(card_number=t.receiver_card_number).first()

            if not sender_card or not receiver_card:
                return get_rpc_error(32718, lang=lang)

            # Qabul qiluvchining balansida pul yetarli ekanligini tekshirish (qaytarib olish uchun)
            if receiver_card.balance < t.sending_amount:
                return get_rpc_error(32719, lang=lang) # Balans yetarli emas

            # Pulni qaytarish operatsiyasi
            receiver_card.balance -= t.sending_amount
            sender_card.balance += t.sending_amount
            
            receiver_card.save()
            sender_card.save()
            
            t.state = 'cancelled'
            t.cancelled_at = timezone.now()
            t.save()
            
            # Muvaffaqiyatli bekor qilingani haqida xabar (32715 odatda success kodi deb olingan bo'lsa)
            return Success({"ext_id": ext_id, "state": "cancelled", "message": "Pul qaytarildi"})

        # --- AGAR HALI TASDIQLANMAGAN (CREATED) BO'LSA ---
        t.state = 'cancelled'
        t.cancelled_at = timezone.now()
        t.save()
        
        return Success({"ext_id": ext_id, "state": "cancelled"})

@method
def check_balance(context, **params):
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    card_expire = params.get("card_expire")
    
    card = Card.objects.filter(card_number=card_number, expire=card_expire).first()
    if not card: 
        return get_rpc_error(32704, lang=lang)

    # --- KARTA TURINI ANIQLASH ---
    c_str = str(card_number)
    card_type = "UNKNOWN"
    # Humo: 9860
    if c_str.startswith('9860'): 
        card_type = "HUMO"
    # Uzcard: 8600, 5614, 6262, 5445
    elif c_str.startswith(('8600', '5614', '6262', '5445')): 
        card_type = "UZCARD"
    # Visa: 4
    elif c_str.startswith('4'): 
        card_type = "VISA"
    # MasterCard: 51, 52, 53, 54, 55 (5614 dan tashqari)
    elif c_str.startswith(('51', '52', '53', '54', '55')):
        card_type = "MASTERCARD"
    # -----------------------------

    owner_masked = (card.owner.get_full_name())

    bal_msgs = {
        'uz': f"Balans: {card.balance:,.2f} UZS",
        'ru': f"Баланс: {card.balance:,.2f} UZS",
        'en': f"Balance: {card.balance:,.2f} UZS"
    }

    return Success({
        "owner": owner_masked,
        "card": card_mask(card_number),
        "card_type": card_type, 
        "balance": float(card.balance), 
        "card_expire": card.expire,
        "message": bal_msgs.get(lang, bal_msgs['uz'])
    })



@method
def card_block_request(context, **params):
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    
    card = Card.objects.filter(card_number=card_number).first()
    if not card: 
        return get_rpc_error(32718, lang=lang)

    if card.status != 'active':
        error_msgs = {
            'uz': "Karta allaqachon bloklangan yoki faol emas.",
            'ru': "Карта уже заблокирована или не активна.",
            'en': "Card is already blocked or not active."
        }
        return get_rpc_error(32703, lang=lang, extra_msg=error_msgs.get(lang))

    full_name = card.owner.get_full_name() if card.owner else "Mijoz"
    c_mask = card_mask(card_number)
    
    # 1. Ochiq kodni generatsiya qilish (Faqat Telegramga ketadi)
    otp_raw = str(random.randint(100000, 999999))
    
    # 2. Kodni xeshlash (Bazaga saqlash uchun)
    otp_hash_value = hashlib.sha256(otp_raw.encode()).hexdigest()
    
    # 3. OTP obyektini yaratish
    otp_log = OTP.objects.create(
        user=card.owner, 
        card=card, 
        purpose=OTP.Purpose.BLOCK, # Model ichidagi Enum dan foydalanish yaxshi praktika
        otp_hash=otp_hash_value,    # <--- Modelizdagi haqiqiy maydon nomi
        expires_at=timezone.now() + timedelta(minutes=2),
        is_used=False
    )

    # 4. Telegramga OCHIQ KODNI yuborish
    tg_msgs = {
        'uz': f"🛡 <b>KARTANI BLOKLASH</b>\n\nHurmatli <b>{full_name}</b>,\nKarta: <b>{c_mask}</b>\nKod: <code>{otp_raw}</code>",
        'ru': f"🛡 <b>БЛОКИРОВКА КАРТЫ</b>\n\nУважаемый(-ая) <b>{full_name}</b>,\nКарта: <b>{c_mask}</b>\nКод: <code>{otp_raw}</code>",
        'en': f"🛡 <b>BLOCK CARD</b>\n\nDear <b>{full_name}</b>,\nCard: <b>{c_mask}</b>\nCode: <code>{otp_raw}</code>"
    }
    send_telegram_message(CHAT_ID, TOKEN, tg_msgs.get(lang, tg_msgs['uz']))

    return Success({"status": "otp_sent", "message": "OTP yuborildi"})


@method
def card_block_confirm(context, **params):
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    otp = params.get("otp")

    card = Card.objects.filter(card_number=card_number).first()
    if not card: 
        return get_rpc_error(32718, lang=lang)

    otp_log = OTP.objects.filter(card=card, purpose="Card Block", is_used=False).last()

    if not otp_log or not otp_log.verify_otp(otp):
        return get_rpc_error(32712, lang=lang)

    # --- STATUS VA VIZUAL CHIROQNI O'ZGARTIRISH ---
    card.status = 'blocked'
    
    # Admin paneldagi 'check_block_status' (yashil chiroq) blocked_until'ga qaraydi.
    # Uni qizil qilish uchun muddatni juda uzoq kelajakka surib qo'yamiz (masalan, 100 yil).
    card.blocked_until = timezone.now() + timezone.timedelta(days=365*100)
    
    card.save() 
    # ----------------------------------------------

    otp_log.is_used = True
    otp_log.save()

    full_name = card.owner.get_full_name() if card.owner else "Mijoz"
    c_mask = card_mask(card_number)
    
    response_msgs = {
        'uz': f"Hurmatli {full_name}, {c_mask} kartangiz bloklandi.",
        'ru': f"Уважаемый(-ая) {full_name}, ваша карта {c_mask} заблокирована.",
        'en': f"Dear {full_name} , your card {c_mask} has been blocked."
    }

    return Success({
        "status": "success",
        "message": response_msgs.get(lang, response_msgs['uz'])
    })


@method
def card_delete_request(context, **params):
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    
    # 1. Kartani bazadan qidirish
    card = Card.objects.filter(card_number=card_number).first()
    if not card: 
        return get_rpc_error(32718, lang=lang)
    
    # 3. Xavfsizlik: Balansda pul bo'lsa o'chirmaslik
    if card.balance > 0:
        balance_error_msgs = {
            'uz': f"Kartangizda mablag' bor ({card.balance:,.2f} UZS), kartani o'chirib bo'lmaydi. Avval mablag'ni yechib oling.",
            'ru': f"На вашей карте есть средства ({card.balance:,.2f} UZS), карту нельзя удалить. Сначала выведите средства.",
            'en': f"There are funds on your card ({card.balance:,.2f} UZS), the card cannot be deleted. Withdraw the funds first."
        }
        # Shunchaki string emas, Success obyekti ichida lug'at qaytaramiz
        return Success({
            "status": "error",
            "message": balance_error_msgs.get(lang, balance_error_msgs['uz'])
        })

    # 2. Karta holatini tekshirish
    if hasattr(card, 'status') and card.status == 'deleted':
        error_msgs = {
            'uz': "Bu karta allaqachon o'chirilgan.",
            'ru': "Эта карта уже удалена.",
            'en': "This card is already deleted."
        }
        return get_rpc_error(32703, lang=lang, extra_msg=error_msgs.get(lang))

    # 3. OTP generatsiya qilish (Ochiq holdagi kod)
    otp_raw = str(random.randint(100000, 999999))
    full_name = card.owner.get_full_name() if card.owner else "Mijoz"
    c_mask = card_mask(card_number)

    # 4. KODNI XESHLASH (Modeldagi otp_hash uchun)
    otp_hash_value = hashlib.sha256(otp_raw.encode()).hexdigest()

    # 5. OTPni bazaga SAQLASH
    # Avvalgi ishlatilmagan o'chirish kodlarini bekor qilish
    OTP.objects.filter(card=card, purpose=OTP.Purpose.DELETE, is_used=False).update(is_used=True)

    otp_log = OTP.objects.create(
        user=card.owner, 
        card=card, 
        purpose=OTP.Purpose.DELETE, # Enum ishlatish xatolarni oldini oladi
        otp_hash=otp_hash_value,    # <--- 'code' o'rniga 'otp_hash' ishlatildi
        expires_at=timezone.now() + timedelta(minutes=2),
        is_used=False
    )

    # 6. Telegram orqali OCHIQ KODNI yuborish
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



@method
def card_delete_confirm(context, **params):
    lang = params.get("lang", "uz").lower()
    card_number = params.get("card_number")
    otp = params.get("otp")

    # 1. Kartani qidirish
    card = Card.objects.filter(card_number=card_number).first()
    if not card: 
        return get_rpc_error(32718, lang=lang)

    # 2. OTPni tekshirish
    otp_log = OTP.objects.filter(card=card, purpose="Card Delete", is_used=False).last()
    if not otp_log or not otp_log.verify_otp(otp):
        return get_rpc_error(32712, lang=lang)



    # 4. MA'LUMOTLARNI SAQLAB QOLISH (Karta o'chib ketishidan oldin)
    full_name = card.owner.get_full_name() if card.owner else "Mijoz"
    c_mask = card_mask(card_number)

    # 5. BAZADAN O'CHIRISH
    # Diqqat: OTP qolishi uchun OTP modelida card field null=True bo'lishi shart!
    card.delete() 
    
    # OTPni ishlatilgan deb belgilaymiz (agar u CASCADE bo'lmasa saqlanib qoladi)
    otp_log.is_used = True
    otp_log.save()

    # 6. JAVOB QAYTARISH
    response_msgs = {
        'uz': f"Hurmatli {full_name}, {c_mask} kartangiz bazadan butunlay o'chirildi.",
        'ru': f"Уважаемый(-ая) {full_name}, ваша карта {c_mask} полностью удалена из базы.",
        'en': f"Dear {full_name}, your card {c_mask} has been permanently deleted from the database."
    }

    return Success({
        "status": "permanently_deleted",
        "message": response_msgs.get(lang, response_msgs['uz'])
    })


