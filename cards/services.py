import csv, logging
from openpyxl import load_workbook
from .models import Card
from . import utils

logger = logging.getLogger(__name__)



def export_cards(filters=None, output_file='cards_export.csv'):
    queryset = Card.objects.all()
    
    if filters:
        query_params = {}
        for key, value in filters.items():
            if key == 'status':
                query_params[key] = value
            else:
                query_params[f"{key}__icontains"] = value
        
        queryset = queryset.filter(**query_params)

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Karta raqami', 'Muddati', 'Telefon', 'Status', 'Balans', 'Yaratilgan vaqt'])
        
        for card in queryset:
            writer.writerow([
                card.card_number,
                card.expire,
                card.phone or '',
                card.get_status_display(),
                card.balance,
                card.created_at.strftime("%Y-%m-%d %H:%M")
            ])
            
    return queryset.count()




def import_cards(excel_file):
    wb = load_workbook(excel_file, data_only=True)
    rows = list(wb.active.iter_rows(min_row=2, values_only=True))
    success, errors = 0, []

    for idx, row in enumerate(rows, 2):
        try:
            num = utils.format_card(row[0])
            if not num: raise ValueError("Karta raqami xato")
            
            Card.objects.update_or_create(
                card_number=num,
                defaults={
                    'expire': utils.format_expire(row[1]),
                    'phone': utils.format_phone(row[2]),
                    'status': row[3] if row[3] in ['active', 'inactive', 'expired'] else 'active',
                    'balance': utils.format_balance(row[4])
                }
            )
            success += 1
        except Exception as e:
            errors.append(f"Qator {idx}: {str(e)}")
            
    return success, errors[:5]



def send_card_messages(status='active', lang='UZ'):
    cards = Card.objects.filter(status=status)
    for card in cards:
        msg = utils.prepare_message(card, lang=lang)
        print(f"SENDING TO {card.phone}: {msg}")
        logger.info(f"Sent to {card.card_number}")
    return cards.count()