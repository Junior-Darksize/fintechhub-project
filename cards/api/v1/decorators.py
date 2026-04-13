import time
import logging
from functools import wraps
from decimal import Decimal

# Loyiha uchun maxsus audit logerini yaratamiz
logger = logging.getLogger('fintech_audit')

def audit_logger(func):
    """
    Har bir funksiya chaqiruvini avtomatik log qiluvchi dekorator.

    Args:
        func (callable): Dekoratsiya qilinadigan funksiya.

    Returns:
        callable: Log yozuvchi dekoratsiyalangan funksiya.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        """
        Ichki o'ram (wrapper) funksiya. Funksiya chaqiruvini logga yozadi va xatolarni tutadi.

        Args:
            *args: Asosiy funksiya argumentlari (odatda context, params va h.k.).
            **kwargs: Asosiy funksiya kalitli argumentlari.

        Returns:
            Any: Asosiy funksiyaning natijasi.
        Raises:
            Exception: Asosiy funksiya ichidagi istalgan xatolikni yuqoriga uzatadi.
        """
        start_time = time.time() # Funksiya boshlangan vaqtni saqlaymiz
        
        # --- IP MANZILNI ANIQLASH (Xavfsizlik uchun muhim) ---
        ip_address = 'unknown'
        context = args[0] if args else {}

        # Django request ob'ektini har xil joylardan (args yoki context) qidirib topadi
        request = None
        if isinstance(context, dict):
            request = context.get('request') or context.get('http_request')
        elif hasattr(context, 'request'):
            request = context.request
        
        # Agar request topilmasa, argumentlar ichidan META ma'lumotlarini qidiradi
        if not request:
            for arg in args:
                if hasattr(arg, 'META'):
                    request = arg
                    break

        # IP manzilni Proxy (X-Forwarded-For) yoki to'g'ridan-to'g'ri (REMOTE_ADDR) oladi
        if request and hasattr(request, 'META'):
            x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded:
                ip_address = x_forwarded.split(',')[0].strip()
            else:
                ip_address = request.META.get('REMOTE_ADDR', 'unknown')
        # -----------------------------------------------

        # Funksiyaga yuborilgan parametrlarni saqlab oladi
        params_data = args[1] if len(args) > 1 else kwargs

        # So'rov boshlanganini va kimdan kelganini logga yozadi
        logger.info(f"===> [CALL] {func.__name__.upper()} | IP: {ip_address}")
        logger.info(f"     [DATA] {params_data}")

        try:
            # Asosiy funksiyani (masalan: pul o'tkazish funksiyasini) ishga tushiradi
            response = func(*args, **kwargs)
            duration = round(time.time() - start_time, 4) # Jarayon davomiyligini hisoblaydi
            
            # --- XAVFSIZ LOG YOZISH ---
            # Javob ob'ekti murakkab bo'lishi mumkin, uni xavfsiz tarzda matnga o'tkazadi
            try:
                if hasattr(response, 'value'):
                    res_str = str(response.value)
                else:
                    res_str = repr(response) # Obyektning qisqacha ko'rinishini oladi
            except Exception:
                res_str = "<Unstrignable Response Object>"

            # Natijani va ketgan vaqtni logga yozadi
            logger.info(f"<=== [RESP] {func.__name__.upper()} | Time: {duration}s")
            logger.info(f"     [RESULT] {res_str[:500]}") # Log fayl to'lib ketmasligi uchun 500 ta belgi bilan cheklaydi
            logger.info("-" * 50)
            
            return response

        except Exception as e:
            # Agar funksiya ichida xato yuz bersa, uni tutib oladi va xato haqida log yozadi
            duration = round(time.time() - start_time, 4)
            logger.error(f"!!!! [ERROR] {func.__name__.upper()} | Time: {duration}s | MSG: {repr(e)}")
            logger.error("-" * 50)
            raise e # Xatoni to'xtatib qo'ymasdan, yuqoriga qayta uzatadi

    return wrapper