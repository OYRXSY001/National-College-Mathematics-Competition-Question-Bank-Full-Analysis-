import posixpath
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from . import throttle


class SecurityHeadersMiddleware:
    """为所有响应附加 Content-Security-Policy（XSS 纵深防御）。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.CONTENT_SECURITY_POLICY:
            response.headers.setdefault(
                "Content-Security-Policy", settings.CONTENT_SECURITY_POLICY
            )
        return response


class ThrottleMiddleware:
    """登录/注册限流的阻断端：屏蔽键命中时对敏感 POST 直接 429。

    计数在 throttle.py 的信号接收器里累加（登录失败/成功）；
    注册计数由 accounts.views 调用 register_attempt() 累加。
    桌面单机版通过 DJANGO_RATELIMIT=0 整体关闭。
    """

    SENSITIVE_POST_PATHS = ("/account/login", "/account/register", "/admin/login")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            settings.RATELIMIT_ENABLED
            and request.method == "POST"
            and request.path.rstrip("/") in self.SENSITIVE_POST_PATHS
        ):
            ip = throttle.client_ip(request)
            username = request.POST.get("username", "")
            if throttle.is_login_blocked(request, username=username):
                return HttpResponse(
                    "尝试过于频繁，请 15 分钟后再试。", status=429,
                    content_type="text/plain; charset=utf-8",
                )
        return self.get_response(request)


class AdminIpAllowlistMiddleware:
    """/admin/ 可选 IP 白名单：设置 DJANGO_ADMIN_ALLOWED_IPS 后生效，
    白名单之外的请求一律 403（对公网部署防止管理后台被爆破/扫描）。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        allowed = settings.ADMIN_ALLOWED_IPS
        if allowed and request.path.startswith("/admin/"):
            if throttle.client_ip(request) not in allowed:
                return HttpResponse(status=403)
        return self.get_response(request)


class LoginRequiredMiddleware:
    """站点门禁：未登录的访问一律先落在登录页，登录后才进主界面。

    放行范围刻意收窄：登录/注册页、Django admin、静态资源与媒体文件。
    其余路径（含原生 PDF 下载）都需要登录。判断前先做 POSIX 归一化，
    避免 /static/../papers/ 这类未归一化路径绕过门禁。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            return self.get_response(request)

        path = posixpath.normpath(request.path)
        if path.startswith(settings.STATIC_URL) or path.startswith(settings.MEDIA_URL):
            return self.get_response(request)
        if path.startswith("/admin/") or path.startswith("/account/"):
            return self.get_response(request)

        login_url = reverse("accounts:login")
        return redirect(f"{login_url}?{urlencode({'next': request.path})}")