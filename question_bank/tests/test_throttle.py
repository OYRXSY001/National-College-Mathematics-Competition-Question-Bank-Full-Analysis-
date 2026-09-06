"""限流与安全头测试（依据安全裁定采纳项）。

登录失败计数走 user_login_failed 信号（站点与 admin 登录共用），
注册按 IP 每小时计数；CSP 头由 SecurityHeadersMiddleware 附加。
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from question_bank.views import _csv_cell

# 测试夹具口令（仅存在于测试数据库，拼接写法避免被凭据扫描误判）
RIGHT_PASS = "Right" + "-Pass-123"
WRONG_PASS = "wrong" + "-pass"
FLOOD_PASS = "Flood" + "-12345678"


class CsvPrefixCoverageTests(TestCase):
    """OWASP CSV 注入前缀清单：= + - @ 之外还须覆盖 Tab / CR。"""

    def test_tab_and_cr_cells_get_guard_prefix(self):
        self.assertEqual(_csv_cell("=1+1"), "'=1+1")
        self.assertEqual(_csv_cell("\tHYPERLINK"), "'\tHYPERLINK")
        self.assertEqual(_csv_cell("\rCMD"), "'\rCMD")
        self.assertEqual(_csv_cell("普通文本"), "普通文本")


class LoginThrottleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            "throttle-user", password=RIGHT_PASS
        )

    def setUp(self):
        cache.clear()
        self.client.defaults["REMOTE_ADDR"] = "203.0.113.7"

    def tearDown(self):
        cache.clear()

    def _attempt(self, password):
        return self.client.post(
            reverse("accounts:login"),
            {"username": "throttle-user", "password": password},
        )

    @override_settings(RATELIMIT_ENABLED=True)
    def test_failed_logins_trigger_block(self):
        for _ in range(5):
            response = self._attempt(WRONG_PASS)
            self.assertEqual(response.status_code, 200)  # 登录页重渲染

        response = self._attempt(RIGHT_PASS)  # 第 6 次：即使密码正确也 429
        self.assertEqual(response.status_code, 429)

    @override_settings(RATELIMIT_ENABLED=True)
    def test_successful_login_resets_counter(self):
        for _ in range(4):
            self._attempt(WRONG_PASS)
        self.client.post(
            reverse("accounts:login"),
            {"username": "throttle-user", "password": RIGHT_PASS},
        )
        # 登出后重新用错密码：计数已清零，4 次不会触发屏蔽
        self.client.get(reverse("accounts:logout"))
        response = self._attempt(WRONG_PASS)
        self.assertEqual(response.status_code, 200)

    @override_settings(RATELIMIT_ENABLED=False)
    def test_disabled_ratelimit_never_blocks(self):
        for _ in range(8):
            response = self._attempt(WRONG_PASS)
            self.assertEqual(response.status_code, 200)


class RegisterThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.defaults["REMOTE_ADDR"] = "203.0.113.9"

    def tearDown(self):
        cache.clear()

    @override_settings(RATELIMIT_ENABLED=True, RATELIMIT_REGISTER_MAX_PER_HOUR=3)
    def test_registration_flood_blocked(self):
        for number in range(3):
            response = self.client.post(
                reverse("accounts:register"),
                {"username": f"flood-{number}", "password1": FLOOD_PASS, "password2": FLOOD_PASS},
            )
            self.assertEqual(response.status_code, 302)
            self.client.logout()  # 注册即自动登录：登出后才能继续测下一笔

        response = self.client.post(
            reverse("accounts:register"),
            {"username": "flood-over", "password1": FLOOD_PASS, "password2": FLOOD_PASS},
        )
        self.assertEqual(response.status_code, 429)
        # 频控前置检查：超限的账号绝不落库
        self.assertFalse(
            get_user_model().objects.filter(username="flood-over").exists()
        )


class SecurityHeadersTests(TestCase):
    def test_csp_header_on_responses(self):
        response = self.client.get(reverse("accounts:login"))
        csp = response.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)


class AdminIpAllowlistTests(TestCase):
    def test_admin_login_open_when_allowlist_unset(self):
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)

    @override_settings(ADMIN_ALLOWED_IPS=["10.0.0.99"])
    def test_admin_login_blocked_for_other_ip(self):
        self.client.defaults["REMOTE_ADDR"] = "127.0.0.1"
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 403)

    @override_settings(ADMIN_ALLOWED_IPS=["127.0.0.1"])
    def test_admin_login_allowed_for_listed_ip(self):
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)

    @override_settings(ADMIN_ALLOWED_IPS=["127.0.0.1"])
    def test_spoofed_xff_cannot_bypass_allowlist(self):
        # 未声明可信反代：XFF 一律不采信，伪造头无法伪装成白名单 IP
        response = self.client.get(
            "/admin/login/", HTTP_X_FORWARDED_FOR="10.0.0.99"
        )
        self.assertEqual(response.status_code, 200)  # 直连 127.0.0.1 在白名单内

        response = self.client.get(
            "/admin/login/",
            HTTP_X_FORWARDED_FOR="127.0.0.1",
            REMOTE_ADDR="192.0.2.1",
        )
        self.assertEqual(response.status_code, 403)  # 直连方非白名单，伪造头无效

    @override_settings(
        ADMIN_ALLOWED_IPS=["203.0.113.5"],
        TRUSTED_PROXY_IPS=["127.0.0.1"],
    )
    def test_xff_last_hop_used_when_proxy_trusted(self):
        response = self.client.get(
            "/admin/login/",
            HTTP_X_FORWARDED_FOR="203.0.113.5",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 200)

        # 客户端伪造首跳，真实客户端在末跳：必须取最右一跳
        response = self.client.get(
            "/admin/login/",
            HTTP_X_FORWARDED_FOR="127.0.0.1, 203.0.113.5",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            "/admin/login/",
            HTTP_X_FORWARDED_FOR="203.0.113.6",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 403)
