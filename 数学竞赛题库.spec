# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from PyInstaller.building.splash import Splash

datas = [('packaging_tmp/db.sqlite3', '.'), ('templates', 'templates'), ('static', 'static'), ('media', 'media')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('django')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('markdown')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tzdata')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('question_bank')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('accounts')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('config')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['run_bank.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# ---- 动态启动画面：给官方生成的 Tcl 脚本追加动画元素 ----
# 官方脚本负责：底图、IPC（update_text/close）、窗口定位——全部保留。
# 状态文字不用官方的 text_pos 机制（bootloader 会往官方文字项里刷解包文件路径，
# 且不走变量 trace 没法过滤），改为自建文字项 mytext + 自建 status_text trace：
# 只接受 run_bank.py 里 pyi_splash.update_text 发来的阶段文案（不含路径分隔符）。
# 坐标对应 splash.png：画布 640x400，徽标圆心 (320,148) 静态环半径 46，
# 进度轨道 y=343..348 x=32..608，状态文字锚点 (32,382)
from PyInstaller.building import splash_templates

_SPLASH_ANIMATION_TCL = r"""
set _spin_a 0
set _spin_b 150
set _bar_x -90
.root.canvas create arc 264 92 376 204 -start 0 -extent 100 -style arc -outline #8F7BFF -width 3 -tag spinA
.root.canvas create arc 256 84 384 212 -start 150 -extent 40 -style arc -outline #FF6EC7 -width 2 -tag spinB
.root.canvas create rectangle -90 343 -10 348 -fill #9F8BFF -width 0 -tag loadbar
.root.canvas create rectangle -90 344 -10 347 -fill #ECE9FF -width 0 -tag loadcore
font create myFont {*}[font actual TkDefaultFont]
font configure myFont -size 13
.root.canvas create text 32 382 -fill #BDB6F2 -justify left -font myFont -tag mytext -anchor sw -text "正在准备运行环境…"
proc _tick {} {
    global _spin_a _spin_b _bar_x
    set _spin_a [expr {($_spin_a + 10) % 360}]
    set _spin_b [expr {($_spin_b - 7) % 360}]
    set _bar_x [expr {((($_bar_x + 7) + 90) % 780) - 90}]
    .root.canvas itemconfigure spinA -start $_spin_a
    .root.canvas itemconfigure spinB -start $_spin_b
    .root.canvas coords loadbar $_bar_x 343 [expr {$_bar_x + 80}] 348
    .root.canvas coords loadcore $_bar_x 344 [expr {$_bar_x + 80}] 347
    after 33 _tick
}
set _pulse_c 0
proc _pulse {} {
    global _pulse_c
    set _pulse_c [expr {($_pulse_c + 1) % 2}]
    .root.canvas itemconfigure mytext -fill [lindex {#BDB6F2 #E7E3FF} $_pulse_c]
    after 650 _pulse
}
after 33 _tick
after 650 _pulse
proc _status_relay {args} {
    if {[string first "\\" $::status_text] == -1 && [string first "/" $::status_text] == -1} {
        .root.canvas itemconfigure mytext -text $::status_text
    }
}
trace add variable status_text write _status_relay
"""

_orig_build_script = splash_templates.build_script

def _build_script_with_animation(text_options=None, always_on_top=False):
    return _orig_build_script(
        text_options=text_options, always_on_top=always_on_top
    ) + _SPLASH_ANIMATION_TCL

splash_templates.build_script = _build_script_with_animation

# 启动画面：640x400 PNG。text_pos 不传（官方文字项不创建，见上）；状态文字由动画块自建
splash = Splash(
    'packaging_assets/splash.png',
    binaries=a.binaries,
    datas=a.datas,
    minify_script=False,
    name='splash',
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    # 官方模板要求：Splash 依赖的 Tcl/Tk DLL 必须显式打进归档，
    # 否则引导阶段报 "SPLASH: could not find requirement tk86t.dll in archive"
    splash.binaries,
    [],
    name='数学竞赛题库',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX 压缩历史上会损坏 Splash 依赖的 Tcl/Tk DLL，宁可不压
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon='packaging_assets/icon_pi.ico',  # 全息玻璃 π（packaging_assets/icon_pi.html 渲染）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
