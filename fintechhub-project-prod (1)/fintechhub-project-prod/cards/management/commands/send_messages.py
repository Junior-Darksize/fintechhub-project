from django.core.management.base import BaseCommand
from cards.services import send_card_messages

class Command(BaseCommand):
    help = 'Filtrlangan kartalarga xabar yuborish'

    def add_arguments(self, parser):
        parser.add_argument('--status', default='active', choices=['active', 'inactive', 'expired'])
        parser.add_argument('--chat_id', type=int, default=12345)
        parser.add_argument('--lang', default='UZ', choices=['UZ', 'RU', 'EN'])

    def handle(self, *args, **options):
        count = send_card_messages(
            status=options['status'],
            lang=options['lang']

        )
        self.stdout.write(self.style.SUCCESS(f'Jarayon yakunlandi: {count} ta xabar simulyatsiya qilindi.'))