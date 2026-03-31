from django.core.management.base import BaseCommand
from cards.models import Error

class Command(BaseCommand):
    help = "Dastlabki xatolik kodlarini Error modeliga yuklash"

    def handle(self, *args, **kwargs):
        # Ro'yxat ko'rinishidagi xatoliklar (List of Dictionaries)
        ERROR_CODES_DATA = [
            {
                "code": 32700,
                "en": "Ext id must be unique",
                "ru": "Ext id должен быть уникальным",
                "uz": "Ext id noyob bo'lishi kerak"
            },
            {
                "code": 32701,
                "en": "Ext id already exists",
                "ru": "Ext id уже существует",
                "uz": "Ext id allaqachon mavjud"
            },
            {
                "code": 32702,
                "en": "Balance is not enough",
                "ru": "Недостаточно средств",
                "uz": "Hisobda mablag' yetarli emas"
            },
            {
                "code": 32703,
                "en": "SMS service is not bind",
                "ru": "SMS сервис не подключен",
                "uz": "SMS xizmati ulanmagan"
            },
            {
                "code": 32704,
                "en": "Card expiry is not valid",
                "ru": "Срок действия карты недействителен",
                "uz": "Karta amal qilish muddati noto'g'ri"
            },
            {
                "code": 32705,
                "en": "Card is not active",
                "ru": "Карта неактивна",
                "uz": "Karta faol emas"
            },
            {
                "code": 32706,
                "en": "Unknown error occurred",
                "ru": "Произошла неизвестная ошибка",
                "uz": "Noma'lum xatolik yuz berdi"
            },
            {
                "code": 32707,
                "en": "Currency not allowed except uzs, rub, usd",
                "ru": "Разрешены только валюты uzs, rub, usd",
                "uz": "Faqat uzs, rub, usd valyutalari ruxsat etilgan"
            },
            {
                "code": 32708,
                "en": "Amount is greater than allowed",
                "ru": "Сумма превышает допустимую",
                "uz": "Miqdor ruxsat etilgan chegaradan katta"
            },
            {
                "code": 32709,
                "en": "Amount is small",
                "ru": "Сумма слишком мала",
                "uz": "Miqdor juda kichik"
            },
            {
                "code": 32710,
                "en": "OTP expired",
                "ru": "OTP истек",
                "uz": "OTP muddati tugagan"
            },
            {
                "code": 32711,
                "en": "Count of try is reached",
                "ru": "Превышено количество попыток",
                "uz": "Urinishlar soni tugadi"
            },
            {
                "code": 32712,
                "en": "OTP is wrong",
                "ru": "Неверный OTP",
                "uz": "Noto'g'ri Kod"
            },
            {
                "code": 32713,
                "en": "Method is not allowed",
                "ru": "Метод не разрешён",
                "uz": "Usulga ruxsat berilmagan"
            },
            {
                "code": 32714,
                "en": "Method not found",
                "ru": "Метод не найден",
                "uz": "Usul topilmadi"
            },
            {
                "code": 32715,
                "en": "Funds have been successfully refunded",
                "ru": "Средства успешно возвращены",
                "uz": "Mablag' muvaffaqiyatli qaytarildi"
            },
            {
                "code": 32716,
                "en": "Card is temporarily blocked.",
                "ru": "Карта временно заблокирована. ",
                "uz": "Karta vaqtincha bloklangan."
            },
            {
                "code": 32717,
                "uz": "Siz tizimga ulandingiz va sizning barcha kartalaringizda SMS xizmati muvaffaqiyatli yoqildi.",
                "ru": "Вы вошли в систему, и на всех ваших картах успешно включен СМС-сервис.",
                "en": "You have logged in, and the SMS service has been successfully enabled on all your cards."
            },
  
            {
                "code": 32718,
                "en": "Invalid card number",
                "ru": "Неверный номер карты",
                "uz": "Karta raqami noto'g'ri"
            },
            {
                "code": 32719,
                "en": "Card has expired",
                "ru": "Сrok действия карты истек",
                "uz": "Karta amal qilish muddati tugagan"
            },
            {
                "code": 32720,
                "en": "Phone number is not linked to this card",
                "ru": "Номер телефона не привязан к этой карте",
                "uz": "Ushbu kartaga telefon raqami biriktirilmagan"
            },
            {
                "code": 32721,
                "en": "Security delay: Card is temporarily locked for outgoing transfers (1 min).",
                "ru": "Задержка безопасности: Карта временно заблокирована для переводов (1 мин).",
                "uz": "Xavfsizlik choralari: Karta 1 daqiqa davomida pul yuborishdan cheklangan."
            },
            {
                "code": 32722,
                "uz": "Telefon raqami, ism yoki familiya noto'g'ri kiritilgan.",
                "ru": "Неверно введен номер телефона, имя или фамилия.",
                "en": "Invalid phone number, first name, or last name."
            },
            {
                "code": 32723,
                "uz": "Foydalanuvchi allaqachon tizimga ulangan.",
                "ru": "Пользователь уже подключен к системе.",
                "en": "The user is already connected to the system."
            },
            {
                "code": 32724,
                "uz": "Urinishlar soni tugadi. Foydalanuvchi 5 daqiqaga bloklandi.",
                "ru": "Количество попыток исчерпано. Пользователь заблокирован на 5 минут.",
                "en": "Number of attempts exhausted. The user is blocked for 5 minutes."
            },
            {
                "code": 32725,
                "uz": "Foydalanuvchi bloklangan. Blokdan chiqishga qolgan vaqt:",
                "ru": "Пользователь заблокирован. Время до разблокировки:",
                "en": "The user is blocked. Time remaining until unlock:"
            }
        ]


        for item in ERROR_CODES_DATA:
            error, created = Error.objects.update_or_create(
                code=item["code"],
                defaults={
                    'en': item["en"],
                    'ru': item["ru"],
                    'uz': item["uz"]
                }
            )
            status = "yaratildi" if created else "yangilandi"
            self.stdout.write(self.style.SUCCESS(f"Kod {item['code']} {status}."))