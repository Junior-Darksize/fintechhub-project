from django.db import models
from .utils import card_mask

class Card(models.Model):
    STATUS_CHOICES = [('active', 'Active'), ('inactive', 'Inactive'), ('expired', 'Expired')]
    
    card_number = models.CharField(max_length=16, unique=True)
    expire = models.CharField(max_length=7)
    phone = models.CharField(max_length=15, blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{card_mask(self.card_number)} ({self.status})"