import csv, logging
from openpyxl import load_workbook
from .models import Card
from . import utils 
from .utils import format_card, format_expire, format_phone, format_balance


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




def import_cards(file):
    if not file:
        return 0, ["Fayl tanlanmagan"]
    
    try:
        wb = load_workbook(file, data_only=True)
        sheet = wb.active
        success_count = 0
        errors = []


        STATUS_MAP = {
            'active': 'active',
            'faol': 'active',
            'inactive': 'inactive',
            'faol emas': 'inactive',
            'expired': 'expired',
            'muddati otgan': 'expired',
        }


        rows = sheet.iter_rows(min_row=2, values_only=True)

        for row_idx, row in enumerate(rows, start=2):
            raw_card = row[0]
            

            if not raw_card or "card" in str(raw_card).lower():
                continue


            num = format_card(raw_card)
            expire = format_expire(row[1])
            phone = format_phone(row[2])
            

            raw_status = str(row[3]).lower().strip() if row[3] else 'active'
            current_status = STATUS_MAP.get(raw_status, 'active')
            
            balance = format_balance(row[4])


            if not num:
                errors.append(f"{row_idx}-qatorda karta raqami xato (16 raqam yoki Luhn): {raw_card}")
                continue

            try:
                Card.objects.update_or_create(
                    card_number=num,
                    defaults={
                        'expire': expire,
                        'phone': phone,
                        'balance': balance,
                        'status': current_status 
                    }
                )
                success_count += 1
            except Exception as e:
                errors.append(f"{row_idx}-qatorda bazaga saqlashda xato: {str(e)}")

        return success_count, errors

    except Exception as e:
        return 0, [f"Excel o'qishda jiddiy xato: {str(e)}"]




def send_card_messages(status='active', lang='UZ'):
    cards = Card.objects.filter(status=status)
    for card in cards:
        msg = utils.prepare_message(card, lang=lang)
        print(f"SENDING TO {card.phone}: {msg}")
        logger.info(f"Sent to {card.card_number}")
    return cards.count()