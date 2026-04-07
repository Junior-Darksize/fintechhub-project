import os
from celery import Celery
from celery.schedules import crontab

# Django sozlamalarini yuklaymiz
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fintechhub.settings')

app = Celery('fintechhub')

# Sozlamalarni Django settings.py dan oladi
app.config_from_object('django.conf:settings', namespace='CELERY')

# Avtomatik ravishda tasklarni qidiradi
app.autodiscover_tasks()

# Davriy topshiriqlar jadvali (Scheduler)
app.conf.beat_schedule = {
    'send-daily-report-at-9am': {
        'task': 'cards.tasks.send_telegram_report',
        'schedule': crontab(hour=17, minute=57),  # Har kuni soat 9:00 da ishga tushadi
    },
}
