from django.conf import settings
from django.contrib.auth import login
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from question_bank import throttle

from .forms import RegistrationForm


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    if (
        request.method == "POST"
        and settings.RATELIMIT_ENABLED
        and throttle.is_login_blocked(request)
    ):
        return HttpResponse(
            "尝试过于频繁，请稍后再试。", status=429,
            content_type="text/plain; charset=utf-8",
        )
    ip = throttle.client_ip(request)
    # 注册频控放在 form.save() 之前：超限时账号绝不落库（否则第 N+1 个
    # 账号仍会被创建，可经正常登录流程使用）
    if request.method == "POST" and settings.RATELIMIT_ENABLED:
        if throttle.register_count(ip) >= settings.RATELIMIT_REGISTER_MAX_PER_HOUR:
            return HttpResponse(
                "注册尝试过于频繁，请稍后再试。", status=429,
                content_type="text/plain; charset=utf-8",
            )
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        if settings.RATELIMIT_ENABLED:
            throttle.register_attempt(ip)
        login(request, user)
        return redirect("home")
    return render(request, "account/register.html", {"form": form})
