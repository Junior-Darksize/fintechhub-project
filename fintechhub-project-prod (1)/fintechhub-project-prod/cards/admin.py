from django.contrib import admin, messages
from django.shortcuts import render, redirect
from .models import Card
from .services import import_cards
from .utils import card_mask, phone_mask

@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ['formatted_card', 'expire', 'formatted_phone', 'status', 'balance']
    list_filter = ['status', 'expire']
    search_fields = ['card_number', 'phone']
    change_list_template = "admin/cards/card_change_list.html"

    def formatted_card(self, obj): return card_mask(obj.card_number)
    def formatted_phone(self, obj): return phone_mask(obj.phone)
    
    formatted_card.short_description = "Karta"
    formatted_phone.short_description = "Telefon"

    def get_urls(self):
        from django.urls import path
        return [path('import-excel/', self.import_excel, name='import_excel')] + super().get_urls()

    def import_excel(self, request):
        if request.method == "POST":
            success, errors = import_cards(request.FILES.get('excel_file'))
            messages.success(request, f"{success} ta karta saqlandi.")
            if errors: messages.error(request, f"Xatolar: {', '.join(errors)}")
            return redirect("..")
        return render(request, "admin/cards/import_excel.html")