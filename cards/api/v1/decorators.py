import time
import logging
from functools import wraps
from decimal import Decimal

logger = logging.getLogger('fintech_audit')

def audit_logger(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        
        # --- IP MANZILNI ANIQLASH ---
        ip_address = 'unknown'
        context = args[0] if args else {}

        request = None
        if isinstance(context, dict):
            request = context.get('request') or context.get('http_request')
        elif hasattr(context, 'request'):
            request = context.request
        
        if not request:
            for arg in args:
                if hasattr(arg, 'META'):
                    request = arg
                    break

        if request and hasattr(request, 'META'):
            x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded:
                ip_address = x_forwarded.split(',')[0].strip()
            else:
                ip_address = request.META.get('REMOTE_ADDR', 'unknown')
        # -----------------------------------------------

        params_data = args[1] if len(args) > 1 else kwargs

        logger.info(f"===> [CALL] {func.__name__.upper()} | IP: {ip_address}")
        # Parol yoki karta raqami kabi nozik ma'lumotlarni logda ko'rsatmaslik yaxshi amaliyot
        logger.info(f"     [DATA] {params_data}")

        try:
            response = func(*args, **kwargs)
            duration = round(time.time() - start_time, 4)
            
            # --- XAVFSIZ LOG YOZISH (Tuzatilgan qism) ---
            # oslash.Either obyekti bo'lsa str() xato berishi mumkin, 
            # shuning uchun response.value yoki repr() ishlatamiz.
            try:
                if hasattr(response, 'value'):
                    res_str = str(response.value)
                else:
                    res_str = repr(response) # str() o'rniga repr() xavfsizroq
            except Exception:
                res_str = "<Unstrignable Response Object>"

            logger.info(f"<=== [RESP] {func.__name__.upper()} | Time: {duration}s")
            logger.info(f"     [RESULT] {res_str[:500]}")
            logger.info("-" * 50)
            
            return response

        except Exception as e:
            duration = round(time.time() - start_time, 4)
            # Bu yerda ham str(e) xavfsizroq formatda
            logger.error(f"!!!! [ERROR] {func.__name__.upper()} | Time: {duration}s | MSG: {repr(e)}")
            logger.error("-" * 50)
            raise e

    return wrapper