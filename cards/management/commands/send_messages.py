from django.core.management.base import BaseCommand  # Django buyruqlar bazasini yuklaydi
from cards.services import send_card_messages        # Xabar yuborish biznes logikasini yuklaydi

class Command(BaseCommand):
    # Terminalda 'python manage.py help [buyruq_nomi]' yozilganda ko'rinadigan tavsif
    help = 'Filtrlangan kartalarga xabar yuborish'

    def add_arguments(self, parser):
        """
        Konsol buyruq parametrlarini qo'shadi.

        Parserga status, chat_id va lang argumentlarini qo'shadi.
        """
        # Terminaldan argumentlar (sozlamalar) qabul qilish:
        # --status: Kartalarni holati bo'yicha saralaydi (default: faqat faol kartalar)
        parser.add_argument('--status', default='active', choices=['active', 'inactive', 'expired'])
        
        # --chat_id: Xabar yuboriladigan Telegram chat identifikatori (default qiymat bilan)
        parser.add_argument('--chat_id', type=int, default=12345)
        
        # --lang: Xabarlar qaysi tilda bo'lishini belgilaydi (UZ, RU, EN)
        parser.add_argument('--lang', default='UZ', choices=['UZ', 'RU', 'EN'])

    def handle(self, *args, **options):
        """
        Karta xabarlarini yuborish jarayonini ishga tushiradi.

        Terminalga natijani yozadi va yuborilgan xabarlar sonini qaytaradi.
        """
        # Asosiy ishchi qism: terminaldan olingan parametrlar bilan funksiyani chaqiradi
        count = send_card_messages(
            status=options['status'], # Tanlangan status
            lang=options['lang']      # Tanlangan til
        )
        
        # Terminalga muvaffaqiyatli yakunlangani haqida yashil rangda xabar chiqaradi
        self.stdout.write(self.style.SUCCESS(f'Jarayon yakunlandi: {count} ta xabar simulyatsiya qilindi.'))