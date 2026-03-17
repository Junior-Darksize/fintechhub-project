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
            excel_file = request.FILES.get('excel_file')
            if not excel_file:
                messages.error(request, "Iltimos, faylni tanlang.")
                return redirect(".")

            success, errors = import_cards(excel_file)
            
            if success > 0:
                messages.success(request, f"{success} ta karta muvaffaqiyatli saqlandi.")
            
            if errors:
                for error in errors[:10]:
                    messages.error(request, error)
                if len(errors) > 10:
                    messages.warning(request, f"Yana {len(errors)-10} ta xato bor...")
            
            return redirect("..")
        return render(request, "admin/cards/import_excel.html")