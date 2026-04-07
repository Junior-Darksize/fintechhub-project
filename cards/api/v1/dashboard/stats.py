import logging
from django.utils import timezone
from django.db.models import Sum
from jsonrpcserver import method, Success
from cards.models import Card, Transfer
from cards.utils import card_mask, get_rpc_error
from cards.api.v1.decorators import audit_logger

# Bank standartida logger
logger = logging.getLogger('fintech_audit')

# Ushbu metod tizimning umumiy moliyaviy holati va tranzaksiyalar 
# statistikasini hisoblab beruvchi tahliliy (Analytics) RPC hisoblanadi.
@method
@audit_logger
def get_advanced_insights(context, **params):
    """
    Kengaytirilgan tahlil va dashboard statistikasi.

    Mantiq:
    1. 'target' parametriga qarab kartalar yoki tranzaksiyalar ro'yxatini shakllantiradi.
    2. 'Card.objects.select_related' orqali DB so'rovlarini optimallashtiradi.
    3. 'Transfer' modelidan faqat 'confirmed' holatidagi pul o'tkazmalarini ajratib oladi.
    4. Django 'Sum' va 'aggregate' funksiyalari yordamida 7 kunlik, 30 kunlik va 
       umumiy aylanma summalarini (Volume) hisoblaydi.
    5. Xavfsizlik uchun hamma joyda 'card_mask' funksiyasi qo'llaniladi.

    Args:
        target (str): 'cards' (kartalar) yoki 'transfers' (tranzaksiyalar).
        lang (str): Til kodi.

    Returns:
        Success: Filtrlangan ro'yxat va umumiy dashboard statistikasi.
    """
    target = params.get('target', 'cards')
    lang = params.get('lang', 'uz')
    now = timezone.now()

    # --- 1. KARTALAR BO'YICHA MA'LUMOT YIG'ISH ---
    if target == 'cards':
        # Select related orqali N+1 muammosini oldini olish
        queryset = Card.objects.select_related('owner').all()
        
        results = []
        for c in queryset:
            results.append({
                "card_number": card_mask(c.card_number),
                "balance": float(c.balance),
                "status": c.status,
            })

    # --- 2. TRANZAKSIYALAR BO'YICHA MA'LUMOT YIG'ISH ---
    else:
        # Oxirgi tranzaksiyalar birinchi keladi
        queryset = Transfer.objects.all().order_by('-created_at')

        results = []
        for t in queryset:
            results.append({
                "ext_id": t.ext_id,
                "sender": card_mask(t.sender_card_number),
                "receiver": card_mask(t.receiver_card_number),
                "amount": float(t.sending_amount),
                "state": t.state,
                "date": t.created_at.strftime("%Y-%m-%d %H:%M")
            })

    # --- 3. DASHBOARD AGGREGATSIYASI (STATISTIKA) ---
    # Anti-Fraud: Faqat muvaffaqiyatli yakunlangan pullarni hisoblaymiz
    confirmed_transfers = Transfer.objects.filter(state='confirmed')

    # Vaqt oraliqlari (Time-series analysis)
    last_7_days = now - timezone.timedelta(days=7)
    last_30_days = now - timezone.timedelta(days=30)

    # Django Aggregation: Bazaning o'zida hisoblash (tezkor)
    total_all = confirmed_transfers.aggregate(s=Sum('sending_amount'))['s'] or 0
    total_7d = confirmed_transfers.filter(created_at__gte=last_7_days).aggregate(s=Sum('sending_amount'))['s'] or 0
    total_30d = confirmed_transfers.filter(created_at__gte=last_30_days).aggregate(s=Sum('sending_amount'))['s'] or 0

    summary = {
        "total_active_cards": Card.objects.filter(status='active').count(),
        "total_transfers_count": Transfer.objects.count(),
        "amounts": {
            "total_sum": float(total_all),
            "last_7_days_sum": float(total_7d),
            "last_30_days_sum": float(total_30d),
            "currency": "UZS"
        },
        "high_balance_cards": Card.objects.filter(balance__gt=1000).count(),
    }

    return Success({
        "count": len(results),
        "data": results,
        "summary": summary
    })