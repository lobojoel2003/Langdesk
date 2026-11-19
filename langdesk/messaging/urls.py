from django.urls import path

from . import views

app_name = "messaging"

urlpatterns = [
    path("sms/twilio/", views.twilio_inbound, name="twilio"),
    path("sms/inbound/", views.generic_inbound, name="inbound"),
    path("sms/simulator/", views.simulator, name="simulator"),
]
