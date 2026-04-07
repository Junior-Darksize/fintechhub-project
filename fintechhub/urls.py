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



@csrf_exempt
def rpc_handler(request):
    # 1. So'rov metodini tekshirish
    if request.method != "POST":
        return JsonResponse({"error": "Faqat POST so'rovlar qabul qilinadi"}, status=405)

    # 2. Request body bo'sh emasligini tekshirish
    body = request.body.decode().strip()
    if not body:
        return JsonResponse({
            "jsonrpc": "2.0",
            "error": {"code": -32700, "message": "Parse error: Empty body"},
            "id": None
        })

    # 3. Dispatch va xatolikni tutib qolish
    try:
        raw_response = dispatch(body, context={'request': request})
        
        # Agar dispatch string qaytarsa (odatda shunday bo'ladi)
        if isinstance(raw_response, str):
            final_response = json.loads(raw_response)
        else:
            final_response = raw_response

        return JsonResponse(final_response, safe=False)

    except json.JSONDecodeError:
        return JsonResponse({
            "jsonrpc": "2.0",
            "error": {"code": -32700, "message": "Parse error: Invalid JSON"},
            "id": None
        })

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/rpc/', rpc_handler, name='rpc_api'),
]
