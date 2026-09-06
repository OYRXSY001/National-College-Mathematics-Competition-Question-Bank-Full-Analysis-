"""登录/注册限流（依据安全裁定采纳项，零第三方依赖）。

机制：
- 登录失败（含 admin 登录）按 (IP, 用户名) 与 IP 两个维度计数；
  达到阈值后写入屏蔽键，中间件对后续 POST 直接 429。
- 登录成功清零对应计数。
- 注册按 IP 每小时计数，由 accounts.views 调用 register_attempt()/register_blocked()。

存储走 Django 默认缓存（LocMemCache）：gunicorn 多 worker 时计数按进程独立，
实际阈值会按 worker 数放大，属可接受的近似限流；如需精确限流请换共享缓存后端。
"""
import logging

from django.conf import settings
from django.contrib.auth.signals import user_login_failed, user_logged_in
from django.core.cache import cache
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def client_ip(request):
    """客户端 IP：仅当直连方（REMOTE_ADDR）属于已声明的可信反代
    （settings.TRUSTED_PROXY_IPS）时才采信 X-Forwarded-For，并取最右一跳
    作为真实客户端；其余情况一律用 REMOTE_ADDR。
    否则伪造 XFF 头即可绕过 admin IP 白名单与登录/注册限流。"""
    remote_addr = request.META.get("REMOTE_ADDR", "")
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff and remote_addr in settings.TRUSTED_PROXY_IPS:
        hops = [hop.strip() for hop in xff.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    return remote_addr


def _login_keys(ip, username):
    return (f"rl:fail:{ip}:{username}", f"rl:fail:{ip}")


def is_login_blocked(request, username=""):
    if not settings.RATELIMIT_ENABLED:
        return False
    ip = client_ip(request)
    if cache.get(f"rl:block:{ip}"):
        return True
    if username and cache.get(f"rl:block:{ip}:{username}"):
        return True
    return False


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request=None, **kwargs):
    if not settings.RATELIMIT_ENABLED or request is None:
        return
    ip = client_ip(request)
    username = str(credentials.get("username") or "")
    max_user = settings.RATELIMIT_LOGIN_MAX_FAILURES
    max_ip = settings.RATELIMIT_IP_MAX_FAILURES
    seconds = settings.RATELIMIT_BLOCK_SECONDS

    pair_key, ip_key = _login_keys(ip, username)
    pair_failures = (cache.get(pair_key) or 0) + 1
    ip_failures = (cache.get(ip_key) or 0) + 1
    cache.set(pair_key, pair_failures, seconds)
    cache.set(ip_key, ip_failures, seconds)

    if pair_failures >= max_user:
        cache.set(f"rl:block:{ip}:{username}", "1", seconds)
        logger.warning("登录限流：IP=%s 用户名=%s 连续失败 %s 次，屏蔽 %s 秒",
                       ip, username, pair_failures, seconds)
    if ip_failures >= max_ip:
        cache.set(f"rl:block:{ip}", "1", seconds)
        logger.warning("登录限流：IP=%s 累计失败 %s 次，屏蔽 %s 秒",
                       ip, ip_failures, seconds)


@receiver(user_logged_in)
def _on_login_success(sender, request=None, user=None, **kwargs):
    if request is None:
        return
    ip = client_ip(request)
    for key in _login_keys(ip, user.get_username() if user else ""):
        cache.delete(key)
    cache.delete(f"rl:fail:{ip}")


def register_attempts_key(ip):
    return f"rl:reg:{ip}"


def register_count(ip):
    """当前 IP 本小时内已注册次数（只读，供 save 之前的前置检查）。"""
    return cache.get(register_attempts_key(ip)) or 0


def register_attempt(ip):
    """注册成功一次：计数 +1，返回是否已超出每小时上限。"""
    key = register_attempts_key(ip)
    count = (cache.get(key) or 0) + 1
    cache.set(key, count, 3600)
    return count > settings.RATELIMIT_REGISTER_MAX_PER_HOUR
