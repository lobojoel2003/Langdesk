from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

from langdesk.version import build_info


def healthz(request):
    """Liveness and readiness for load balancers and ``docker compose`` health checks."""
    status, code = "ok", 200
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database = "ok"
    except Exception:
        status, code, database = "degraded", 503, "unavailable"
    return JsonResponse({"status": status, "database": database, **build_info()}, status=code)


def handler404(request, exception):
    return render(request, "404.html", status=404)


def handler500(request):
    return render(request, "500.html", status=500)


def handler403(request, exception):
    return render(request, "403.html", status=403)
