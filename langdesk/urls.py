from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from langdesk.core.views import healthz
from langdesk.scheduling.views import home

admin.site.site_header = "Langdesk administration"
admin.site.site_title = "Langdesk"
admin.site.index_title = "Roster and records"

urlpatterns = [
    path("", home, name="home"),
    path("healthz", healthz, name="healthz"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "accounts/password/",
        auth_views.PasswordChangeView.as_view(),
        name="password_change",
    ),
    path(
        "accounts/password/done/",
        auth_views.PasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
    path("admin/", admin.site.urls),
    path("reports/", include("langdesk.reports.urls")),
    path("", include("langdesk.messaging.urls")),
    path("", include("langdesk.scheduling.urls")),
]

handler403 = "langdesk.core.views.handler403"
handler404 = "langdesk.core.views.handler404"
handler500 = "langdesk.core.views.handler500"
