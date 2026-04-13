import re
from stdnum import luhn
from decimal import Decimal, ROUND_HALF_UP
import requests
from jsonrpcserver import Error
import random
import hashlib
from django.utils import timezone
from datetime import timedelta

import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

# .env dan kalitni olamiz
key = os.getenv("ENCRYPTION_KEY")
cipher = Fernet(key.encode())

def encrypt_card(card_number: str) -> str:
    """
    Karta raqamini shifrlaydi (Database uchun).

    Args:
        card_number (str): Karta raqami (16 xonali yoki string).

    Returns:
        str: Shifrlangan karta raqami (base64).
    """
    return cipher.encrypt(card_number.encode()).decode()

def decrypt_card(encrypted_number: str) -> str:
    """
    Shifrlangan karta raqamini ochadi (decryption).

    Args:
        encrypted_number (str): Shifrlangan karta raqami (base64).

    Returns:
        str: Asl karta raqami (16 xonali string).
    """
    return cipher.decrypt(encrypted_number.encode()).decode()


def _clean_digits(value):
    """
    Matndan faqat raqamlarni ajratib oladi (Regex yordamida).

    Args:
        value (Any): Matn yoki raqamli qiymat.

    Returns:
        str: Faqat raqamlar (string ko'rinishida).
    """
    return re.sub(r'\D', '', str(value)) if value else ""

def is_luhn_valid(card_number):
    """
    Luhn algoritmi orqali karta raqami haqiqiyligini tekshiradi.

    Args:
        card_number (str|int): Karta raqami (string yoki raqam).

    Returns:
        bool: True agar karta raqami haqiqiy bo'lsa, aks holda False.
    """
    cleaned = _clean_digits(card_number)
    return luhn.is_valid(cleaned) if cleaned else False

def format_card(raw_card):
    """
    Karta raqamini 16 xonali standart formatga keltiradi.

    Args:
        raw_card (str): Kiritilgan karta raqami (har qanday formatda).

    Returns:
        str|None: 16 xonali karta raqami yoki None.
    """
    cleaned = _clean_digits(raw_card)
    
    if len(cleaned) != 16:
        return None
        
    # if not is_luhn_valid(cleaned):
    #     return None
        
    return cleaned

def format_phone(raw_phone):
    """
    Telefon raqamini 9 xonali standart formatga keltiradi.

    Args:
        raw_phone (str): Telefon raqami (har qanday formatda).

    Returns:
        str|None: 9 xonali telefon raqami yoki None.
    """
    cleaned = _clean_digits(raw_phone)
    if not cleaned: return None
    return cleaned[-9:] if len(cleaned) >= 9 else cleaned


def format_expire(raw_expire):
    """
    Karta muddatini (01/27, 2027.01 va h.k.) MM/YY formatiga o'tkazadi.

    Args:
        raw_expire (str): Karta muddati (har qanday formatda).

    Returns:
        str|None: MM/YY formatidagi muddat yoki None.
    """
    if not raw_expire: return None
    raw_expire = str(raw_expire).strip()
    parts = re.split(r'[-./]', raw_expire)
    if len(parts) != 2: return raw_expire
    
    p1, p2 = parts[0].zfill(2), parts[1].zfill(2)
    return f"{p1}/{p2[-2:]}" if len(p1) == 2 else f"{p2}/{p1[-2:]}"



def format_balance(raw_balance):
    """
    Har xil formatdagi balansni Decimal (o'nlik kasr) ko'rinishiga keltiradi.

    Args:
        raw_balance (Any): Balans qiymati (str, float, int va h.k.).

    Returns:
        Decimal: Balans Decimal ko'rinishida.
    """
    if raw_balance is None: return Decimal('0.00')
    try:
        clean_val = re.sub(r'[^\d.]', '', str(raw_balance))
        return Decimal(clean_val) if clean_val else Decimal('0.00')
    except:
        return Decimal('0.00')



def mask_name(full_name):
    """
    Ism va familiyani A**** B**** ko'rinishida maskalaydi.

    Args:
        full_name (str): To'liq ism va familiya.

    Returns:
        str: Maskalangan ism va familiya.
    """
    parts = full_name.split()
    masked_parts = []
    for part in parts:
        if len(part) > 1:
            masked_parts.append(part[0] + "*" * (len(part) - 1))
        else:
            masked_parts.append(part)
    return " ".join(masked_parts)




def card_mask(card_number):
    """
    Karta raqamining o'rta qismini yashiradi (Xavfsizlik uchun).

    Args:
        card_number (str): Karta raqami.

    Returns:
        str: Maskalangan karta raqami.
    """
    return f"{card_number[:4]} **** **** ** {card_number[-2:]}" if card_number else ""



def phone_mask(phone):
    """
    Telefon raqamini maskalaydi (Masalan: +998 ** *** **55).

    Args:
        phone (str): Telefon raqami.

    Returns:
        str: Maskalangan telefon raqami.
    """
    return f"+998 ** *** **{phone[-2:]}" if phone else "Noma'lum"





def send_telegram_message(chat_id, token, text):
    """
    Telegram Bot API orqali HTML formatida xabar yuboradi.

    Args:
        chat_id (str|int): Telegram chat ID.
        token (str): Bot tokeni.
        text (str): Yuboriladigan xabar matni (HTML formatda).

    Returns:
        dict|None: Telegram API javobi yoki None.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(url, data={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'})
        return response.json()
    except Exception as e:
        print(f"Telegram error: {e}")
        return None



def prepare_message(card, lang="UZ"):
    """
    Karta holati haqida ko'p tilli (UZ, RU, EN) xabar matnini shakllantiradi.

    Args:
        card (Card): Card modeli obyekti.
        lang (str, optional): Til kodi ('UZ', 'RU', 'EN'). Standarti 'UZ'.

    Returns:
        str: Tayyorlangan xabar matni.
    """

    translations = {
        'UZ': {
            'template': "Sizning {card} kartangiz {status} va balans: {balance} UZS.",
            'active': 'aktiv',
            'inactive': 'faol emas',
            'expired': 'muddati otgan'
        },
        'RU': {
            'template': "Ваша карта {card} {status}, баланс: {balance} UZS.",
            'active': 'активна',
            'inactive': 'не активна',
            'expired': 'истек срок действия'
        },
        'EN': {
            'template': "Your card {card} is {status}, balance: {balance} UZS.",
            'active': 'active',
            'inactive': 'inactive',
            'expired': 'expired'
        }
    }


    lang_data = translations.get(lang.upper(), translations['UZ'])
    
    status_text = lang_data.get(card.status, card.status)
    
    return lang_data['template'].format(
        card=card_mask(card.card_number),
        status=status_text,
        balance=f"{card.balance:,.0f}"
    )



def get_card_type(card_number):
    """
    Karta raqamining boshlanishiga qarab turini aniqlaydi.

    Args:
        card_number (str): Karta raqami.

    Returns:
        str: Karta turi ('HUMO', 'UZCARD', 'VISA', 'MASTERCARD', 'UNKNOWN').
    """
    card_str = str(card_number)
    if card_str.startswith('9860'):
        return "HUMO"
    elif card_str.startswith('8600'):
        return "UZCARD"
    elif card_str.startswith('4'):
        return "VISA"
    elif card_str.startswith('5'):
        return "MASTERCARD"
    else:
        return "UNKNOWN"






def get_rpc_error(code, lang='uz', extra_msg=None):
    """
    Xatolik kodini bazadan qidiradi va JSON-RPC formatidagi xato ob'ektini qaytaradi.
    Bu frontend uchun xatolarni dinamik tillarda ko'rsatish imkonini beradi.

    Args:
        code (int): Xatolik kodi.
        lang (str, optional): Til kodi ('uz', 'ru', 'en'). Standarti 'uz'.
        extra_msg (str, optional): Qo'shimcha xabar.

    Returns:
        Error: JSON-RPC xato obyekti.
    """

    from .models import Error as ErrorModel
    err = ErrorModel.objects.filter(code=code).first()
    
    if err:
        message = err.get_message(lang)
    else:
        message = "System Error"
        
    if extra_msg:
        message = f"{message} {extra_msg}"

    # FAQAT ob'ektni qaytaramiz (raise emas!)
    return Error(code=code, message=message)



def get_live_exchange_rate(currency_code):
    """
    Markaziy Bank (CBU) JSON API-dan joriy valyuta kursini oladi.
    Agar API ishlamasa, fallback (zaxira) kurslardan foydalanadi.

    Args:
        currency_code (str): Valyuta kodi ('UZS', 'USD', 'RUB', ...).

    Returns:
        Decimal: Joriy kurs (1 birlik uchun UZSda).
    """
    currency_code = currency_code.upper()
    if currency_code == "UZS":
        return Decimal("1.0")
    
    try:
        # CBU API-ga so'rov yuboramiz
        response = requests.get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/", timeout=5)
        if response.status_code == 200:
            data = response.json()
            for item in data:
                if item['Ccy'] == currency_code:
                    # Kursni Decimal formatiga o'tkazamiz
                    return Decimal(str(item['Rate']))
    except Exception as e:
        print(f"Kursni olishda xatolik: {e}")
    
    # Agar API ishlamasa, oxirgi ma'lum bo'lgan kurslar (Zaxira)
    fallbacks = {"USD": Decimal("12850.00"), "RUB": Decimal("145.00")}
    return fallbacks.get(currency_code, Decimal("1.0"))