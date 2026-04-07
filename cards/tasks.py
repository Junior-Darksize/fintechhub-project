import logging
import requests
from decimal import Decimal
from celery import shared_task
from django.utils import timezone
from django.db.models import Sum
from .models import Card, Transfer

# Logger sozlamalari
logger = logging.getLogger('fintech_audit')

# Telegram sozlamalari
TG_TOKEN = "8448513005:AAFCmG5C9a2_3Tbh_bDzoXThUfotsTUlx0E"
TG_CHAT_ID = 1078739901

@shared_task
def send_telegram_report():
    """
    Kengaytirilgan kunlik hisobot: Hamma 'amount'lar 'sending_amount'ga o'zgartirildi.
    """
    now = timezone.now()
    last_24h = now - timezone.timedelta(days=1)
    
    logger.info(f"--- Detallashgan hisobot yaratish boshlandi: {now.strftime('%Y-%m-%d %H:%M:%S')} ---")

    try:
        # 1. Umumiy statistika
        total_cards = Card.objects.exclude(status='deleted').count()
        active_cards = Card.objects.filter(status='active').count()
        
        # Oxirgi 24 soatlik barcha transferlar
        transfers_24h = Transfer.objects.filter(created_at__gte=last_24h)
        
        total_transfer_count = transfers_24h.count()
        success_transfers_query = transfers_24h.filter(state='confirmed')
        
        # 2. Umumiy muvaffaqiyatli summa (sending_amount bo'yicha)
        # DIQQAT: Bu yerda 'amount' emas, 'sending_amount' bo'lishi shart!
        total_sum_dict = success_transfers_query.aggregate(total=Sum('sending_amount'))
        total_sum = total_sum_dict.get('total') or 0

        # 3. Transferlar tafsilotlari
        details_text = ""
        if success_transfers_query.exists():
            details_text = "\n🔄 <b>Oxirgi muvaffaqiyatli transferlar:</b>\n"
            # Faqat oxirgi 10 tasini ko'rsatamiz
            for tr in success_transfers_query.order_by('-created_at')[:10]:
                # Karta raqamlarini to'g'ridan-to'g'ri maydondan olamiz
                s_mask = tr.sender_card_number[-4:] if tr.sender_card_number else "????"
                r_mask = tr.receiver_card_number[-4:] if tr.receiver_card_number else "????"
                
                # Bu yerda ham tr.amount emas, tr.sending_amount!
                details_text += f"• 💳 ..{s_mask} ➡️ ..{r_mask} | 💰 {tr.sending_amount:,.0f} UZS\n"
        else:
            details_text = "\nℹ️ <i>Oxirgi 24 soatda muvaffaqiyatli transferlar mavjud emas.</i>"

        # 4. Xabar matni
        report_msg = (
            f"📊 <b>KUNLIK FINTECH HISOBOTI</b>\n"
            f"📅 Sana: {now.strftime('%d.%m.%Y %H:%M')}\n"
            f"───────────────────\n\n"
            f"💳 <b>Kartalar holati:</b>\n"
            f"  • Jami: {total_cards}\n"
            f"  • Aktiv: {active_cards}\n\n"
            f"💸 <b>Transferlar (24s):</b>\n"
            f"  • Jami urinishlar: {total_transfer_count}\n"
            f"  • Muvaffaqiyatli: ✅ {success_transfers_query.count()}\n"
            f"  • Umumiy aylanma: 📈 <b>{total_sum:,.2f} UZS</b>\n"
            f"{details_text}\n"
            f"───────────────────\n"
            f"🤖 <i>Fintech Monitoring System v1.1</i>"
        )

        # 5. Telegramga yuborish
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {
            "chat_id": TG_CHAT_ID,
            "text": report_msg,
            "parse_mode": "HTML"
        }
        
        response = requests.post(url, json=payload, timeout=15)
        
        if response.status_code == 200:
            logger.info("Telegram hisobot muvaffaqiyatli yuborildi.")
        else:
            logger.error(f"Telegram API Error: {response.text}")

    except Exception as e:
        logger.error(f"Report System Error: {str(e)}", exc_info=True)