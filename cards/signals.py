from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from .models import Card, User
from decimal import Decimal
from .utils import card_mask, send_telegram_message

TOKEN = "8448513005:AAFCmG5C9a2_3Tbh_bDzoXThUfotsTUlx0E"
CHAT_ID = 1078739901

# 1. SAQLASHDAN OLDIN: Eski ma'lumotlarni vaqtinchalik xotiraga olamiz
@receiver(pre_save, sender=Card)
def capture_old_values(sender, instance, **kwargs):
    if instance.pk:
        try:
            old_obj = Card.objects.get(pk=instance.pk)
            instance._old_balance = old_obj.balance
            instance._old_sms_status = old_obj.is_sms_enabled
        except Card.DoesNotExist:
            instance._old_balance = None
            instance._old_sms_status = None
    else:
        instance._old_balance = None
        instance._old_sms_status = None

# 2. SAQLAGANDAN KEYIN: Taqqoslab xabar yuboramiz
@receiver(post_save, sender=Card)
def card_change_notification(sender, instance, created, **kwargs):
    # Foydalanuvchi tilini aniqlash
    lang = getattr(instance.owner, 'lang', 'uz').lower() if instance.owner else 'uz'
    
    c_mask = card_mask(instance.card_number)
    new_bal = f"{instance.balance:,.2f} UZS"

    # --- A. SMS XIZMATI YOQILSA (KARTA ULANDI) ---
    old_sms = getattr(instance, '_old_sms_status', False)
    if instance.is_sms_enabled and (created or not old_sms):
        msgs = {
            'uz': f"💳 <b>Yangi karta muvaffaqiyatli ulandi!</b>\nKarta: {c_mask}\nEga: {instance.owner.get_full_name() if instance.owner else 'N/A'}",
            'ru': f"💳 <b>Новая карта успешно добавлена!</b>\nКарта: {c_mask}\nВладелец: {instance.owner.get_full_name() if instance.owner else 'N/A'}",
            'en': f"💳 <b>New card has been successfully added!</b>\nCard: {c_mask}\nOwner: {instance.owner.get_full_name() if instance.owner else 'N/A'}"
        }
        send_telegram_message(CHAT_ID, TOKEN, msgs.get(lang, msgs['uz']))
        return

    # --- B. BALANS O'ZGARSA (KIRIM/CHIQIM) ---
    if instance.is_sms_enabled and hasattr(instance, '_old_balance') and instance._old_balance is not None:
        if instance.balance != instance._old_balance:
            diff = instance.balance - instance._old_balance
            abs_diff = f"{abs(diff):,.2f} UZS"

            if diff > 0: # KIRIM
                msgs = {
                    'uz': f"💰 <b>Kirim: +{abs_diff}</b>\nKarta: {c_mask}\nBalans: {new_bal}",
                    'ru': f"💰 <b>Пополнение: +{abs_diff}</b>\nКарта: {c_mask}\nБаланс: {new_bal}",
                    'en': f"💰 <b>Credit: +{abs_diff}</b>\nCard: {c_mask}\nBalance: {new_bal}"
                }
            else: # CHIQIM
                msgs = {
                    'uz': f"💸 <b>Chiqim: -{abs_diff}</b>\nKarta: {c_mask}\nBalans: {new_bal}",
                    'ru': f"💸 <b>Списание: -{abs_diff}</b>\nКарта: {c_mask}\nБаланс: {new_bal}",
                    'en': f"💸 <b>Debit: -{abs_diff}</b>\nCard: {c_mask}\nBalance: {new_bal}"
                }
            
            send_telegram_message(CHAT_ID, TOKEN, msgs.get(lang, msgs['uz']))