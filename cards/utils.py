import re
from stdnum import luhn
from decimal import Decimal

def _clean_digits(value):
    return re.sub(r'\D', '', str(value)) if value else ""

def format_card(raw_card):
    cleaned = _clean_digits(raw_card)
    if len(cleaned) != 16:
        return None
    # if not luhn.is_valid(cleaned):
    #     return None
    return cleaned

def format_phone(raw_phone):
    cleaned = _clean_digits(raw_phone)
    if not cleaned: return None
    return cleaned[-9:] if len(cleaned) >= 9 else cleaned

def format_expire(raw_expire):
    if not raw_expire: return None
    raw_expire = str(raw_expire).strip()
    parts = re.split(r'[-./]', raw_expire)
    if len(parts) != 2: return raw_expire
    
    p1, p2 = parts[0].zfill(2), parts[1].zfill(2)
    return f"{p1}/{p2[-2:]}" if len(p1) == 2 else f"{p2}/{p1[-2:]}"



def format_balance(raw_balance):
    if raw_balance is None: return Decimal('0.00')
    try:
        clean_val = re.sub(r'[^\d.]', '', str(raw_balance))
        return Decimal(clean_val) if clean_val else Decimal('0.00')
    except:
        return Decimal('0.00')





def card_mask(card_number):
    return f"{card_number[:4]} **** **** ** {card_number[-2:]}" if card_number else ""



def phone_mask(phone):
    return f"+998 ** *** {phone[-4:]}" if phone else "Noma'lum"


def prepare_message(card, lang="UZ"):

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