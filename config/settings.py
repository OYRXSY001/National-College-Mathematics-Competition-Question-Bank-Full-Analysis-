import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 可写数据目录：打包成 exe 后 BASE_DIR 是只读解压目录，数据（数据库/上传文件）
# 必须放到 exe 同目录（由入口脚本注入 BANK_DATA_DIR）；普通开发运行时与 BASE_DIR 相同。
DATA_DIR = Path(os.getenv("BANK_DATA_DIR", str(BASE_DIR)))

DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"

# SECRET_KEY：环境变量优先；否则读取（缺失则生成）数据目录内的持久密钥文件。
# 每个安装/数据目录独立一把密钥，替代公开已知的固定默认值。
# 注意：密钥变化会使已有会话失效（用户需重新登录），属预期行为。
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    _key_path = DATA_DIR / "secret_key.txt"
    try:
        SECRET_KEY = _key_path.read_text(encoding="utf-8").strip()
    except OSError:
        SECRET_KEY = ""
    if not SECRET_KEY:
        import secrets as _secrets

        SECRET_KEY = _secrets.token_urlsafe(64)
        try:
            _key_path.write_text(SECRET_KEY + "\n", encoding="utf-8")
        except OSError:
            if not DEBUG:
                raise RuntimeError(
                    f"无法写入密钥文件 {_key_path}，且未设置 DJANGO_SECRET_KEY 环境变量；"
                    "生产环境必须提供 DJANGO_SECRET_KEY"
                )

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "question_bank",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "question_bank.middleware.SecurityHeadersMiddleware",
    "question_bank.middleware.AdminIpAllowlistMiddleware",
    "question_bank.middleware.ThrottleMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "question_bank.middleware.LoginRequiredMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "question_bank.context_processors.site_info",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

# WAL 模式：读不阻塞写，多请求并发下大幅减少 "database is locked"；
# timeout 为写锁等待秒数（桌面单机几乎无感，公网部署时是主要兜底）
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {
            "init_command": "PRAGMA journal_mode=WAL;",
            "timeout": 20,
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "static",
    BASE_DIR / "static" / "vendor" / "bootstrap",
    BASE_DIR / "static" / "vendor" / "katex",
]

MEDIA_URL = "/media/"
MEDIA_ROOT = DATA_DIR / "media"
REVIEW_ROOT = DATA_DIR / "data" / "review"

# Project attribution shown on every page and the about page.
SITE_AUTHOR = os.getenv("DJANGO_SITE_AUTHOR", "OYRXSY001")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "accounts:login"

CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------- 纵深防御（依据安全裁定采纳项，零第三方依赖） ----------

# 内容安全策略：脚本只允许本站文件（模板已无内联脚本/事件处理器）；
# style 需 unsafe-inline：KaTeX 渲染与若干模板使用内联 style 属性
CONTENT_SECURITY_POLICY = os.getenv(
    "DJANGO_CSP",
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'",
)

# /admin/ 可选 IP 白名单（逗号分隔）；留空 = 不限制
ADMIN_ALLOWED_IPS = [
    ip.strip()
    for ip in os.getenv("DJANGO_ADMIN_ALLOWED_IPS", "").split(",")
    if ip.strip()
]

# 可信反代 IP（逗号分隔）：仅当 REMOTE_ADDR 在此列表内时才采信
# X-Forwarded-For（取最右一跳为真实客户端），防止伪造头绕过白名单/限流。
# Caddy 反代部署（REMOTE_ADDR=127.0.0.1）需设 DJANGO_TRUSTED_PROXIES=127.0.0.1
TRUSTED_PROXY_IPS = [
    ip.strip()
    for ip in os.getenv("DJANGO_TRUSTED_PROXIES", "").split(",")
    if ip.strip()
]

# 登录/注册限流（缓存计数实现；桌面单机版由 run_bank 注入 DJANGO_RATELIMIT=0 关闭）
RATELIMIT_ENABLED = os.getenv("DJANGO_RATELIMIT", "1") == "1"
RATELIMIT_LOGIN_MAX_FAILURES = int(os.getenv("DJANGO_RATELIMIT_LOGIN_MAX", "5"))
RATELIMIT_IP_MAX_FAILURES = int(os.getenv("DJANGO_RATELIMIT_IP_MAX", "20"))
RATELIMIT_BLOCK_SECONDS = int(os.getenv("DJANGO_RATELIMIT_BLOCK_SECONDS", "900"))
RATELIMIT_REGISTER_MAX_PER_HOUR = int(os.getenv("DJANGO_RATELIMIT_REGISTER_MAX", "10"))

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
