from django.urls import path

from . import views

app_name = "scheduling"

urlpatterns = [
    path("board/", views.board, name="board"),
    path("requests/", views.request_list, name="list"),
    path("requests/new/", views.request_new, name="new"),
    path("requests/<int:pk>/", views.request_detail, name="detail"),
    path("requests/<int:pk>/edit/", views.request_edit, name="edit"),
    path("requests/<int:pk>/offer/", views.request_offer, name="offer"),
    path("requests/<int:pk>/assign/", views.request_assign, name="assign"),
    path("requests/<int:pk>/unassign/", views.request_unassign, name="unassign"),
    path("requests/<int:pk>/video/", views.request_video, name="video"),
    path("requests/<int:pk>/cancel/", views.request_cancel, name="cancel"),
    path("requests/<int:pk>/outcome/", views.request_outcome, name="outcome"),
    path("requests/<int:pk>/calendar.ics", views.request_ics, name="ics"),
    path("interpreters/", views.interpreter_list, name="interpreters"),
    path("interpreters/<int:pk>/", views.interpreter_detail, name="interpreter"),
    path("o/<str:token>/", views.offer_respond, name="offer_respond"),
    path("calendar/<str:token>.ics", views.calendar_feed, name="feed"),
]
