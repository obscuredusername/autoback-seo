"""
Signals for the keyword_content app.
"""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

# Import your models here if you need to connect signals to them
# from .models import YourModel

# Example signal handler (uncomment and modify as needed)
# @receiver(post_save, sender=YourModel)
# def your_signal_handler(sender, instance, created, **kwargs):
#     if created:
#         # Do something with the new instance
#         pass
