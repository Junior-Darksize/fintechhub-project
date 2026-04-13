from django.core.management.base import BaseCommand  # Django terminal buyruqlari uchun asosiy klass
from cards.services import export_cards              # Eksport qilish logikasi yozilgan servis funksiyasi

class Command(BaseCommand):
    # Terminalda 'python manage.py help [buyruq_nomi]' yozilganda chiqadigan yordamchi matn
    help = 'Kartalarni CSV formatida eksport qilish'

    def add_arguments(self, parser):
        # Terminaldan yuborilishi mumkin bo'lgan qo'shimcha parametrlar (filtrlash uchun):
        
        # --status: Faqat ma'lum holatdagi (masalan, 'active') kartalarni ajratib olish uchun
        parser.add_argument('--status', help='Status boyicha filtr (active, inactive, expired)')
        
        # --card_number: Ma'lum bir karta raqamini qidirish uchun
        parser.add_argument('--card_number', help='Karta raqami boyicha filtr')
        
        # --phone: Ma'lum bir telefon raqamiga biriktirilgan kartalarni topish uchun
        parser.add_argument('--phone', help='Telefon boyicha filtr')
        
        # --output: Yaratiladigan fayl nomini belgilash (standart holatda: cards_export.csv)
        parser.add_argument('--output', default='cards_export.csv', help='Chiqish fayli nomi')

    def handle(self, *args, **options):
        # 1. Filtrlarni shakllantirish:
        # Terminaldan kelgan barcha parametrlar ichidan faqat status, card_number va phone'ni ajratib oladi.
        # Faqat qiymati bor (bo'sh bo'lmagan) filtrlarni lug'atga (dict) joylaydi.
        filters = {k: v for k, v in options.items() if k in ['status', 'card_number', 'phone'] and v}
        
        # 2. Servis funksiyasini chaqirish:
        # Shakllangan filtrlar va fayl nomi 'export_cards' funksiyasiga uzatiladi.
        count = export_cards(filters, options['output'])
        
        # 3. Natijani ko'rsatish:
        # Jarayon tugagach, terminalda yashil rangda necha dona karta faylga yozilgani haqida xabar chiqadi.
        self.stdout.write(self.style.SUCCESS(f'Muvaffaqiyatli: {count} ta karta "{options["output"]}" fayliga eksport qilindi.'))