# 公网部署安全清单（deploy checklist）

> 依据 2026-09-05/06 专家组安全测评与核证裁定整理。桌面版 exe（127.0.0.1 单用户）
> 无需本清单；本清单面向 **deploy/（Caddy + gunicorn）公网多用户部署**。

## 一、环境变量（/etc/cmc-a.env，systemd EnvironmentFile）

| 变量 | 必填 | 说明 |
|---|---|---|
| `DJANGO_DEBUG` | ✅ | 必须显式设 `0`。**默认就是 1**，忘设 = 调试页泄露 + cookie 不加 Secure + media 由 Django 兜底 |
| `DJANGO_SECRET_KEY` | ✅ | ≥50 位随机串（`python -c "import secrets; print(secrets.token_urlsafe(64))"`）。不设时回落到数据目录 `secret_key.txt`（首启自动生成），env 优先 |
| `DJANGO_ALLOWED_HOSTS` | ✅ | 真实域名，逗号分隔；默认 `127.0.0.1,localhost` 会导致线上 400 |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | ✅ | `https://你的域名`（HTTPS 终止于 Caddy 时必配，否则 POST 全部 403） |
| `DJANGO_TRUSTED_PROXIES` | ✅ | 可信反代 IP（Caddy 反代场景设 `127.0.0.1`）。**不设则 X-Forwarded-For 一律不采信**——这是防止伪造头绕过下面白名单与限流的前提 |
| `DJANGO_ADMIN_ALLOWED_IPS` | 建议 | /admin/ IP 白名单（逗号分隔）；仅当 `DJANGO_TRUSTED_PROXIES` 已设时才按 XFF 末跳判定客户端 IP；留空 = 不限制 |
| `DJANGO_RATELIMIT` | 建议 | 保持默认 `1`（启用登录失败锁定 + 注册频控）；`0` 关闭 |

限流默认阈值：同一 (IP, 用户名) 登录连败 **5** 次、同 IP 累计败 **20** 次 → 屏蔽 **15 分钟**；
同 IP 每小时注册 **10** 个封顶。阈值可用 `DJANGO_RATELIMIT_*` 环境变量调整。
注意：计数存于进程内缓存，gunicorn 多 worker 时实际阈值 ≈ 配置值 × worker 数。

## 二、静态与媒体

- [ ] `python manage.py collectstatic`（Caddyfile 已把 `/static/*` 指到 `/srv/cmc-a/staticfiles`）
- [ ] 了解 media 访问矩阵：`/media/questions/*`（题目配图）由 **Caddy 免登录直出**（有意设计）；
      `/media/papers/*` 公网 404，试卷 PDF 只经需登录的 `paper_download` 视图下发——
      **不要**在 Caddy 加 `/media/papers/*` 直服，也**不要**用 `pdf_file.url` 生成直链
- [ ] 普通用户零上传面（全站无 `request.FILES`）；文件写入仅限 staff（admin，PDF 魔数校验）
      与导入命令（图片目录/扩展名/签名三重校验）

## 三、认证与账号

- [ ] 管理员仅经 `create_admin_account.bat`（交互式 createsuperuser）创建；注册用户 `is_staff=False`，无提权路径
- [ ] 登录无验证码；公网强烈建议叠加 IP 级限流（Caddy `rate_limit` 插件或 WAF）
- [ ] 密码重置链路未实现（注册不采集邮箱）：公网运营需约定人工重置流程，或先扩展
      注册表单收集邮箱 + 配置 SMTP 后挂 `PasswordResetView`

## 四、数据与备份

- [ ] SQLite 已启用 WAL + 20s 写锁等待（settings OPTIONS）；并发写上来后迁移
      PostgreSQL——注意 `微信小程序/data/import/migrate_to_pg.py` 是小程序 openid 体系
      的遗留脚本，**对 Django 部署不可直接使用**，需另行改造
- [ ] `deploy/backup.sh` 每日备份（14 天轮转）；**恢复流程至少演练一次**
- [ ] `secret_key.txt`（若用文件密钥）与 `db.sqlite3` 一样在数据目录内，备份与权限一并管理

## 五、安全头（已内置，核对即可）

- [ ] 响应含 `Content-Security-Policy: default-src 'self'; script-src 'self'; ...`
      （模板已无内联脚本/事件处理器；style 的 `unsafe-inline` 是 KaTeX 与模板内联样式所需）
- [ ] 非 DEBUG 下 HSTS 一年 + Secure cookie + SSL 重定向自动生效
- [ ] gunicorn 仅绑 `127.0.0.1:8000`，公网出口只有 Caddy（`SECURE_PROXY_SSL_HEADER` 依赖此前置）
