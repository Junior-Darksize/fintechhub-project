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




@csrf_exempt
def rpc_handler(request):
    # 1. Metodni ishga tushiramiz
    raw_response = dispatch(request.body.decode(), context={})
    
    # 2. MUHIM: Agarda raw_response string bo'lsa, uni lug'atga aylantiramiz
    if isinstance(raw_response, str):
        final_response = json.loads(raw_response)
    else:
        final_response = raw_response

    # 3. JsonResponse orqali chiroyli formatda qaytaramiz
    return JsonResponse(
        final_response, 
        safe=False, 
        json_dumps_params={'indent': 4} # Bu Postmanda chiroyli (ustma-ust) chiqaradi
    )


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/rpc/', rpc_handler, name='rpc_api'),
]
