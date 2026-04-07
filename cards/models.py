import hashlib
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.utils import timezone
from .utils import card_mask
from django.contrib.auth.hashers import make_password, check_password


class User(AbstractUser):
    first_name = models.CharField(max_length=150, verbose_name="Ism")
    last_name = models.CharField(max_length=150, verbose_name="Familiya")
    phone_number = models.CharField(max_length=15, unique=True, null=True, blank=True)
    lang = models.CharField(max_length=2, default='uz', choices=[('uz', 'Uzbek'), ('ru', 'Russian'), ('en', 'English')])
    blocked_until = models.DateTimeField(null=True, blank=True, verbose_name="Bloklangan vaqti")

    # Migratsiya xatosini yechish uchun related_name qo'shamiz
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='custom_user_set',
        blank=True,
        verbose_name='groups',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='custom_user_permission_set',
        blank=True,
        verbose_name='user permissions',
    )

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        # Agar ism-familiya bo'lmasa, username qaytaradi
        full_name = self.get_full_name()
        return full_name if full_name else self.username



class Card(models.Model):
    # models.py ichida
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('expired', 'Expired'),
        ('blocked', 'Blocked'), 
        ('deleted', 'Deleted'), 
    ]
    
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cards', null=True, blank=True)
    card_number = models.CharField(max_length=16, unique=True)
    expire = models.CharField(max_length=7)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    is_sms_enabled = models.BooleanField(default=False)
    blocked_until = models.DateTimeField(null=True, blank=True)
    otp = models.CharField(max_length=255, null=True, blank=True) # Hashlangan OTP uchun
    try_count = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        owner_name = self.owner.get_full_name() if self.owner else "Egasiz"
        return f"{card_mask(self.card_number)} - {owner_name}"
    
    def is_blocked(self):
        return self.blocked_until and timezone.now() < self.blocked_until



class Transfer(models.Model):
    class State(models.TextChoices):
        CREATED = 'created', 'Created'
        CONFIRMED = 'confirmed', 'Confirmed'
        CANCELLED = 'cancelled', 'Cancelled'

    ext_id = models.CharField(max_length=64, unique=True, db_index=True)
    sender_card_number = models.CharField(max_length=16, db_index=True)
    receiver_card_number = models.CharField(max_length=16, db_index=True)
    sender_card_expiry = models.CharField(
        max_length=5,
        validators=[RegexValidator(r'^(0[1-9]|1[0-2])/[0-9]{2}$', "Format: MM/YY")]
    )
    
    sending_amount = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(1.0)])
    currency = models.CharField(max_length=3, choices=[('860', 'UZS'), ('840', 'USD'), ('643', 'RUB')], default='860')
    receiving_amount = models.DecimalField(max_digits=15, decimal_places=2, editable=False, null=True)
    
    state = models.CharField(max_length=15, choices=State.choices, default=State.CREATED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    otp = models.CharField(max_length=255, null=True, blank=True)
    try_count = models.PositiveSmallIntegerField(default=0)


    def set_otp(self, raw_otp):
        """OTP kodini hashlab saqlaydi"""
        self.otp = make_password(raw_otp)
        self.save()

    def verify_otp(self, raw_otp):
        """Kiritilgan kodni bazadagi hash bilan solishtiradi"""
        if not self.otp:
            return False
        return check_password(raw_otp, self.otp)

    def __str__(self):
        return f"Transfer {self.ext_id} - {self.state}"
    

    def save(self, *args, **kwargs):
        if not self.receiving_amount:
            rates = {'643': Decimal('140.00'), '840': Decimal('12500.00'), '860': Decimal('1.00')}
            self.receiving_amount = self.sending_amount * rates.get(self.currency, Decimal('1.00'))
        
        if self.state == self.State.CONFIRMED and not self.confirmed_at:
            self.confirmed_at = timezone.now()
        super().save(*args, **kwargs)



class OTP(models.Model):
    class Purpose(models.TextChoices):
        LOGIN = "User Login", "User Login"
        TRANSFER = "Money Transfer", "Money Transfer"
        BLOCK = "Card Block", "Card Block"
        DELETE = "Card Delete", "Card Delete"
        BINDING = "Card Binding", "Card Binding" # Karta ulanishi uchun

    user = models.ForeignKey('User', on_delete=models.CASCADE, null=True, blank=True, related_name='otps')
    card = models.ForeignKey('Card', on_delete=models.CASCADE, null=True, blank=True, related_name='card_otps')
    transfer = models.ForeignKey('Transfer', on_delete=models.CASCADE, null=True, blank=True, related_name='transfer_otps')
    
    # SHA-256 xeshi saqlanadigan joy
    otp_hash = models.CharField(max_length=255, editable=False)
    purpose = models.CharField(max_length=50, choices=Purpose.choices, null=True, blank=True)
    expires_at = models.DateTimeField()
    try_count = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def verify_otp(self, input_otp):
        """
        Kiritilgan ochiq kodni (input_otp) SHA-256 orqali xeshlab,
        bazadagi otp_hash bilan solishtiradi.
        """
        # 1. Asosiy tekshiruvlar (Ishlatilganmi, Vaqti o'tganmi, Urinishlar tugaganmi)
        if self.is_used:
            return False
        
        if timezone.now() > self.expires_at:
            return False
            
        if self.try_count >= 3:
            return False
        
        # 2. SHA-256 xesh yaratish (input_otp ni stringga o'tkazish shart)
        input_hash = hashlib.sha256(str(input_otp).encode()).hexdigest()
        
        # 3. Solishtirish
        if input_hash == self.otp_hash:
            self.is_used = True
            self.save()
            return True
        
        # 4. Xato bo'lsa, urinishni oshirish
        self.try_count += 1
        self.save()
        return False

    def __str__(self):
        owner = self.user.get_full_name() if self.user else "Noma'lum"
        return f"{owner} - {self.purpose} ({self.created_at})"
    
    

class Error(models.Model):
    code = models.IntegerField(unique=True, primary_key=True)
    en = models.CharField(max_length=255)
    ru = models.CharField(max_length=255)
    uz = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.code}: {self.uz}"
    
    def get_message(self, lang='uz'):
        return getattr(self, lang, self.uz)
    
