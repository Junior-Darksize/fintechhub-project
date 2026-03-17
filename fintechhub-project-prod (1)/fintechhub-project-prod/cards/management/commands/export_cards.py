from django.core.management.base import BaseCommand
from cards.services import export_cards

class Command(BaseCommand):
    help = 'Kartalarni CSV formatida eksport qilish'

    def add_arguments(self, parser):
        parser.add_argument('--status', help='Status boyicha filtr (active, inactive, expired)')
        parser.add_argument('--card_number', help='Karta raqami boyicha filtr')
        parser.add_argument('--phone', help='Telefon boyicha filtr')
        parser.add_argument('--output', default='cards_export.csv', help='Chiqish fayli nomi')

    def handle(self, *args, **options):
        filters = {k: v for k, v in options.items() if k in ['status', 'card_number', 'phone'] and v}
        
        count = export_cards(filters, options['output'])
        self.stdout.write(self.style.SUCCESS(f'Muvaffaqiyatli: {count} ta karta "{options["output"]}" fayliga eksport qilindi.'))