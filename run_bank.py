#!/usr/bin/env python
"""全国大学生数学竞赛题库 —— 桌面版入口（PyInstaller 打包用）。

打包后双击 exe：先显示启动画面（Splash），同时把内置题库数据（数据库/媒体）
落盘后启动 Django 服务器并自动打开浏览器。数据默认固定存放在
%LOCALAPPDATA%\\MathQuestionBank（不随 exe 位置变化，换目录/挪文件都不丢数据）；
exe 旁放一个空文件 portable.flag 即改为 exe 同目录存储（U 盘便携场景）。
终端控制台不显示（windowed 模式）：所有输出写入数据目录里的 bank.log，
需要人工确认的错误用系统消息框提示。

直接 python run_bank.py 运行效果相同（有控制台、无启动画面），数据存放在项目根目录。

数据目录只由本程序决定：外部遗留的 BANK_DATA_DIR 环境变量不会把用户数据
引到别处，避免"换了目录数据消失"。
"""
import ctypes
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


# ---------- 启动画面（PyInstaller Splash；源码运行时自动降级为无） ----------

try:
    import pyi_splash
except ImportError:  # 非打包环境
    pyi_splash = None


def _splash_text(text: str) -> None:
    if pyi_splash is not None:
        try:
            if pyi_splash.is_alive():
                pyi_splash.update_text(text)
        except Exception:
            pass


def _splash_close() -> None:
    if pyi_splash is not None:
        try:
            pyi_splash.close()
        except Exception:
            pass


# ---------- 无控制台下的日志与提示 ----------

def _redirect_streams(app_dir: Path) -> None:
    """windowed 模式 stdout/stderr 实际是 NUL 设备（不是 None），统一接管到 bank.log
    （>8MB 时重建），既不会丢失输出，也方便日后排查问题。"""
    if not getattr(sys, "frozen", False):
        return
    log_path = app_dir / "bank.log"
    try:
        if log_path.exists() and log_path.stat().st_size > 8 * 1024 * 1024:
            # 改名轮转优于直接删除：被占用（如另一实例）时旧日志得以保留
            try:
                os.replace(log_path, app_dir / "bank.log.old")
            except OSError:
                try:
                    log_path.unlink()
                except OSError:
                    pass  # 仍被占用：退化为继续追加
        stream = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = stream
        sys.stderr = stream
    except OSError:
        pass


def _alert(title: str, message: str) -> None:
    """无控制台环境用系统消息框提示用户；有控制台时打印即可。"""
    print(f"\n  [{title}] {message}", flush=True)
    windll = getattr(ctypes, "windll", None)
    if windll is not None and getattr(sys, "frozen", False):
        try:
            windll.user32.MessageBoxW(None, message, title, 0x40 | 0x3000)  # 信息图标+置顶
        except Exception:
            pass


# ---------- 运行目录与数据落盘 ----------

def _resolve_app_dir() -> Path:
    """运行目录：exe 所在目录；未打包时为脚本所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _bundle_dir() -> Path:
    """PyInstaller 解压出的只读资源目录；未打包时就是项目根。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent


def _writable(path: Path) -> bool:
    probe = path / ".write_probe"
    try:
        probe.write_text("x", encoding="utf-8")
    except OSError:
        return False
    try:
        probe.unlink()
    except OSError:
        pass  # 杀软/同步盘可能瞬时占用探针；能写入即视为可写
    return True


def _process_alive(pid: int) -> bool:
    """Windows 下探测进程是否存活（无 psutil 依赖）。"""
    if not sys.platform.startswith("win"):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, 0, pid
    )
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def _acquire_lock(app_dir: Path) -> bool:
    """单实例锁：拿不到锁说明已有一个实例在运行。

    锁文件第一行为 PID（异常退出残留会自动接管）；第二行为当前服务端口，
    供再次双击时直接打开正在运行的服务。锁文件内容格式: "pid\\nport"。
    """
    lock_path = app_dir / ".bank.lock"
    # 原子排他创建：杜绝"检查-写入"竞态导致的双开（两个进程同时通过 exists 检查）
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        pass
    except OSError:
        return True  # 目录只读时放弃锁（数据目录稍后会回退到用户目录）

    # 锁已存在：判断是否活实例。pid 可能为空（对方刚创建还没写入），稍等重读
    old_pid, old_port = None, None
    for _ in range(10):
        try:
            lines = lock_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        if lines:
            try:
                old_pid = int(lines[0])
                old_port = int(lines[1]) if len(lines) > 1 else None
            except ValueError:
                old_pid, old_port = None, None
            break
        time.sleep(0.05)
    if old_pid and _process_alive(old_pid):
        return _reopen_existing_instance(old_port)
    # 残留锁（进程已死）：接管重写
    try:
        lock_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    except OSError:
        pass
    return True


def _reopen_existing_instance(old_port: int | None) -> bool:
    """题库已在运行：找到它并把浏览器带过去，而不是报错退出。"""
    _splash_close()
    port = old_port
    if port is not None and _http_ready(port):
        webbrowser.open(f"http://127.0.0.1:{port}/papers/")
        return False
    for candidate in range(8000, 8010):
        if _http_ready(candidate):
            webbrowser.open(f"http://127.0.0.1:{candidate}/papers/")
            return False
    _alert("数学竞赛题库已在运行", "检测到题库正在运行，但服务尚未就绪，请稍后再试。")
    return False


def _release_lock(app_dir: Path) -> None:
    lock_path = app_dir / ".bank.lock"
    try:
        if lock_path.read_text(encoding="utf-8").splitlines()[0] == str(os.getpid()):
            lock_path.unlink()
    except OSError:
        pass


# 数据目录由 main() 解析并规范化后写入；退出入口/锁机制只认这个值，
# 不复读环境变量（外部可写 BANK_DATA_DIR 时也不受影响）
_APP_DIR: Path | None = None


def _request_quit() -> None:
    """网页「退出桌面版」入口：清理单实例锁后延迟结束进程（os._exit 不触发 finally）。"""
    app_dir = _APP_DIR or Path.cwd().resolve()
    if any(part == ".." for part in app_dir.parts):  # 兜底防路径穿越
        app_dir = Path.cwd().resolve()
    try:
        _release_lock(app_dir)
    except Exception:
        pass
    threading.Timer(1.0, os._exit, args=(0,)).start()


def _open_data_dir() -> None:
    """网页「打开数据文件夹」入口：在资源管理器里打开数据目录，方便备份/查看。"""
    app_dir = _APP_DIR or Path.cwd().resolve()
    if sys.platform.startswith("win"):
        os.startfile(str(app_dir))  # noqa: S606 - 仅打开本地目录，无参数注入面


def _first_run_setup(app_dir: Path, bundle: Path) -> None:
    """首次运行时把内置数据（题库数据库、试卷配图）复制到可写目录。"""
    # 数据库：已存在即视为已初始化，不覆盖用户数据。
    # 先拷临时文件再原子改名：拷贝中断不会留下半个 db.sqlite3 被当成已有库
    if not (app_dir / "db.sqlite3").exists() and (bundle / "db.sqlite3").exists():
        tmp = app_dir / "db.sqlite3.tmp"
        shutil.copy2(bundle / "db.sqlite3", tmp)
        os.replace(tmp, app_dir / "db.sqlite3")
        print(f"  [首次运行] 已初始化题库数据库 -> {app_dir / 'db.sqlite3'}", flush=True)
    # 媒体文件（试卷配图等）：整体缺失先拷目录，个别缺失的文件再补
    media_src = bundle / "media"
    media_dst = app_dir / "media"
    if media_src.is_dir():
        if not media_dst.exists():
            shutil.copytree(media_src, media_dst)
            print(f"  [首次运行] 已复制媒体文件 -> {media_dst}", flush=True)
        else:
            copied = 0
            for src in media_src.rglob("*"):
                if src.is_file():
                    rel = src.relative_to(media_src)
                    dst = media_dst / rel
                    if not dst.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        copied += 1
            if copied:
                print(f"  [数据修复] 补齐 {copied} 个缺失的媒体文件", flush=True)


# ---------- 服务启动 ----------

def _pick_port(start: int, tries: int = 10):
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return None


_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http_ready(port: int) -> bool:
    """已可服务 HTTP（登录页 / 重定向到界面都算就绪），而非只看端口通。

    显式绕过系统代理：配置了代理的机器上 urlopen 默认会把 127.0.0.1 的请求
    发给远程代理，就绪探测会永远失败。
    """
    try:
        with _NO_PROXY_OPENER.open(
            f"http://127.0.0.1:{port}/account/login/", timeout=1.5
        ) as resp:
            return resp.status in (200, 302)
    except Exception:
        return False


def _serve(port: int, on_bind) -> None:
    """起 HTTP 服务并阻塞（等效 runserver --noreload）。

    不走 runserver 命令：它绑定失败时是 os._exit(1)，外层根本无法换端口重试；
    直接用 Django 的 WSGI 服务器，端口冲突表现为可捕获的普通 OSError。
    on_bind 在端口绑定成功后、开始服务前被调用一次。
    """
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.core.servers import basehttp
    from django.core.wsgi import get_wsgi_application

    handler = StaticFilesHandler(get_wsgi_application())
    basehttp.run("127.0.0.1", port, handler, threading=True, on_bind=on_bind)


def _pick_data_dir() -> Path:
    """数据目录决策。

    - 源码运行：项目根目录（与开发习惯一致）。
    - 打包运行（默认）：固定 %LOCALAPPDATA%\\MathQuestionBank——不随 exe 位置变化，
      避免"压缩包里直接双击（数据进临时目录）""挪动 exe（数据看似丢失）"
      "OneDrive/同步盘锁定 SQLite"三类翻车；每个 Windows 账号独立一份。
    - 便携模式：exe 旁放一个空文件 portable.flag，数据回到 exe 同目录（U 盘场景）。
    """
    exe_dir = _resolve_app_dir().resolve()
    if not getattr(sys, "frozen", False):
        return exe_dir
    if (exe_dir / "portable.flag").exists() and _writable(exe_dir):
        return exe_dir
    appdata = (
        Path(os.environ.get("LOCALAPPDATA", Path.home())).resolve()
        / "MathQuestionBank"
    )
    try:
        appdata.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if _writable(appdata):
        return appdata
    return exe_dir  # 兜底：用户目录不可写时退回 exe 目录


def _migrate_legacy_data(exe_dir: Path, app_dir: Path) -> None:
    """旧版本把数据放在 exe 同目录；新版默认目录变了，自动搬迁一次。

    搬完把旧文件改名保留（*.migrated.bak），既不会重复触发，也不丢原始数据。
    """
    legacy_db = exe_dir / "db.sqlite3"
    if app_dir == exe_dir or not legacy_db.exists():
        return
    if (app_dir / "db.sqlite3").exists():
        return  # 新目录已有数据，绝不动它
    tmp = app_dir / "db.sqlite3.tmp"
    shutil.copy2(legacy_db, tmp)
    os.replace(tmp, app_dir / "db.sqlite3")
    try:
        legacy_db.rename(exe_dir / "db.sqlite3.migrated.bak")
    except OSError:
        pass
    legacy_media = exe_dir / "media"
    dst_media = app_dir / "media"
    if legacy_media.is_dir():
        if not dst_media.exists():
            try:
                shutil.move(str(legacy_media), str(dst_media))
            except OSError:
                pass
        else:
            for src in legacy_media.rglob("*"):
                if src.is_file():
                    rel = src.relative_to(legacy_media)
                    dst = dst_media / rel
                    if not dst.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            shutil.copy2(src, dst)
                        except OSError:
                            pass
            try:
                legacy_media.rename(exe_dir / "media.migrated.bak")
            except OSError:
                pass
    print(f"  [数据迁移] 已把旧版数据从 {exe_dir} 搬到 {app_dir}", flush=True)


def main() -> int:
    global _APP_DIR
    app_dir = _pick_data_dir()
    _APP_DIR = app_dir
    bundle = _bundle_dir()
    os.chdir(app_dir)
    os.environ["BANK_DATA_DIR"] = str(app_dir)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # 打包运行时 DEBUG 强制为 1：接收者机器上残留的 DJANGO_DEBUG=0 会让
    # settings 崩溃或把 http 请求 301 到 https，桌面版直接不可用
    if getattr(sys, "frozen", False):
        os.environ["DJANGO_DEBUG"] = "1"
        # 桌面单机（loopback、单用户）没有暴力破解面，登录限流只会
        # 让输错 5 次密码的用户被锁 15 分钟，故关闭
        os.environ.setdefault("DJANGO_RATELIMIT", "0")
    else:
        os.environ.setdefault("DJANGO_DEBUG", "1")
    # 数据目录定下后再建立日志流（windowed 模式无控制台，必须先接管
    # stdout/stderr，否则后续 print/flush 在 stdout 为 None 时会抛错）
    _redirect_streams(app_dir)

    print("=" * 52, flush=True)
    print("  全国大学生数学竞赛题库 - 桌面版", flush=True)
    print("=" * 52, flush=True)

    if not _acquire_lock(app_dir):
        return 1

    try:
        # 旧版本把数据放 exe 同目录：搬进新目录后再谈"是否已有数据库"
        _splash_text("正在准备题库数据…")
        _migrate_legacy_data(_resolve_app_dir().resolve(), app_dir)
        print(f"  [数据目录] {app_dir}", flush=True)
        if (app_dir / "db.sqlite3").exists():
            print("  [数据状态] 检测到已有数据库，将保留原有记录", flush=True)
        _first_run_setup(app_dir, bundle)

        # 启动前确保数据表结构最新（对已有数据库自动迁移，不影响数据）
        try:
            from django.core.management import execute_from_command_line

            _splash_text("正在初始化数据库…")
            execute_from_command_line(["manage.py", "migrate", "--noinput"])
        except Exception as error:
            _splash_close()
            print(f"  [错误] 数据库迁移失败：{error}", flush=True)
            _alert(
                "题库启动失败",
                "数据库迁移失败：\n"
                f"{error}\n\n"
                "请检查数据目录里的 db.sqlite3 是否被占用或损坏\n"
                f"（目录：{app_dir}，可先备份后删除该文件再试）。",
            )
            return 1

        # 起服务：端口被占（探测与绑定间的竞态）时逐个后移重试。
        # 绑定成功（on_bind）才收启动画面、开浏览器、把实际端口回写锁文件
        _splash_text("正在启动服务…")
        base = int(os.environ.get("BANK_PORT", "8000"))
        for port in range(base, base + 10):
            if not _pick_port(port, 1):
                print(f"  [跳过] 端口 {port} 被占用", flush=True)
                continue

            def on_bind(port=port):
                try:
                    (app_dir / ".bank.lock").write_text(
                        f"{os.getpid()}\n{port}", encoding="utf-8"
                    )
                except OSError:
                    pass  # 锁写失败只影响"再次双击直达"，不影响服务
                url = f"http://127.0.0.1:{port}/papers/"
                print(f"  [网站地址] {url}", flush=True)
                print(f"  [管理后台] http://127.0.0.1:{port}/admin/", flush=True)
                print(
                    "  [退出方式] 打开网页「我的 → 退出桌面版」停止服务（数据保留），"
                    "或直接结束进程",
                    flush=True,
                )
                print("-" * 52, flush=True)
                print(f"  [日志文件] {app_dir / 'bank.log'}", flush=True)
                _splash_close()  # 服务就绪：收起启动画面，交给浏览器
                webbrowser.open(url)

            try:
                _serve(port, on_bind)
                return 0  # 正常停止（网页退出 / Ctrl+C 由上层处理）
            except OSError:
                print(f"  [重试] 端口 {port} 绑定失败，尝试下一个…", flush=True)

        _splash_close()
        _alert("题库启动失败", "8000-8009 端口均被占用，请关闭占用程序后重试。")
        return 1
    finally:
        _release_lock(app_dir)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已停止。")
        sys.exit(0)
    except Exception as error:
        # 兜底：任何未预期异常都要收掉启动画面并给出可见提示（windowed 无控制台）
        _splash_close()
        print(f"  [错误] {error}", flush=True)
        import traceback

        traceback.print_exc()
        _alert(
            "题库启动失败",
            f"发生意外错误：{error}\n\n详细信息见程序同目录的 bank.log。",
        )
        sys.exit(1)