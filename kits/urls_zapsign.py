from django.urls import path
from .views_zapsign import ZapSignWebhookView

urlpatterns = [
    path("webhook/", ZapSignWebhookView.as_view(), name="zapsign-webhook"),
]
