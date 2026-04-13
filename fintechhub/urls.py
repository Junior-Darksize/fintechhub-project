"""
URL configuration for fintechhub project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
import json
from django.views.decorators.csrf import csrf_exempt
from jsonrpcserver import dispatch
from django.http import JsonResponse
import cards.api.v1.rpc_methods
import cards.api.v1.dashboard.stats



@csrf_exempt  # Tashqi tizimlardan (Postman, Frontend) keladigan so'rovlar uchun CSRF himoyasini o'chiradi
def rpc_handler(request):
    # 1. So'rov metodini tekshirish
    # JSON-RPC standarti bo'yicha ma'lumotlar faqat POST orqali yuborilishi shart
    if request.method != "POST":
        return JsonResponse({"error": "Faqat POST so'rovlar qabul qilinadi"}, status=405)

    # 2. Request body (so'rov tanasi) bo'sh emasligini tekshirish
    # Kelgan baytlarni matn ko'rinishiga o'tkazadi va bo'sh joylarni olib tashlaydi
    body = request.body.decode().strip()
    
    # Agar so'rov tanasi bo'sh bo'lsa, JSON-RPC standartidagi "Parse error" xatosini qaytaradi
    if not body:
        return JsonResponse({
            "jsonrpc": "2.0",
            "error": {"code": -32700, "message": "Parse error: Empty body"},
            "id": None
        })

    # 3. Dispatch (Yo'naltirish) va xatolikni tutib qolish
    try:
        # 'dispatch' funksiyasi JSON matnni o'qiydi va ichidagi 'method' nomiga qarab 
        # tegishli funksiyani (masalan: card_create) topib, ishga tushiradi.
        # 'context' orqali har bir funksiya ichida Django 'request' ob'ektidan foydalanish imkonini beradi.
        raw_response = dispatch(body, context={'request': request})
        
        # 'jsonrpcserver' kutubxonasi ba'zida natijani matn (string) ko'rinishida qaytaradi.
        # Agar natija matn bo'lsa, uni Python lug'atiga (dict) aylantiramiz.
        if isinstance(raw_response, str):
            final_response = json.loads(raw_response)
        else:
            final_response = raw_response

        # Tayyor bo'lgan natijani mijozga (Frontend/Postman) JSON formatida qaytaradi
        # safe=False - natija ro'yxat (list) ko'rinishida bo'lsa ham xatolik bermasligi uchun
        return JsonResponse(final_response, safe=False)

    except json.JSONDecodeError:
        # Agar yuborilgan JSON formati buzilgan bo'lsa (masalan, qavslar noto'g'ri bo'lsa)
        # ushbu xatolik tutib qolinadi va standart JSON-RPC xatosi qaytariladi.
        return JsonResponse({
            "jsonrpc": "2.0",
            "error": {"code": -32700, "message": "Parse error: Invalid JSON"},
            "id": None
        })
    

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/rpc/', rpc_handler, name='rpc_api'),
]
