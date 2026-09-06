# 全国大学生数学竞赛题库

📚 基于 Django 的数学竞赛真题题库网站，收录第 1–17 届全国大学生数学竞赛（非数学类 A/B）初赛与决赛真题，共 **39 份试卷、254 道题**，公式使用 KaTeX 渲染，支持在线浏览题目与解析、下载试卷 PDF。

## 项目简介

本项目是面向全国大学生数学竞赛（非数学类 A/B）的真题题库系统，提供 **Web 网站**与**微信小程序**两个端：

- **Web 端（Django）**：在线浏览第 1–17 届初赛/决赛真题试卷与解析，公式使用 KaTeX 渲染，支持下载试卷 PDF，后台支持按届导入与管理题库数据。
- **小程序端（mini-program/）**：微信小程序版题库，内置题目数据与公式渲染组件，支持按试卷、知识点分类浏览和关键词搜索。

## ✨ 功能特性

- 🗂️ 收录第 1–17 届初赛/决赛真题，非数学类 A/B 双分类，共 39 份试卷、254 道题
- 📐 数学公式使用 KaTeX 渲染，Web 与小程序端均可正常显示
- 📄 在线浏览题目与详细解析，支持下载试卷 PDF、**打印整卷**（作答留白版 / 含答案与解析版）
- 🔍 题目检索与知识点分类浏览
- 🎯 练习模式：按试卷 / 知识点 / 全部 / 错题本范围连续刷题，答错自动记入错题本；支持键盘快捷键（1 答对 / 2 答错 / 3 跳过、回车下一题），中途退出可**从上次进度继续**
- 📒 错题本：累计答错次数、最近答错时间、标记已掌握、未掌握/已掌握筛选；**间隔复习排期**（答错次日复习，答对按 1/3/7/15 天推进，连对 4 次自动掌握），列表显示每题“今天要复习 / 下次复习日期”徽章
- 🧠 **智能组卷**：从答错最多的 Top3 知识点随机抽 10–15 题生成薄弱巩固卷；**今日复习**按排期列出到期错题
- 📊 “我的”学习统计：累计作答、正确率、**近 7 天 / 近 30 天**作答分布（一键切换）、薄弱知识点榜单、最近一次模拟考试成绩
- ⏱ **模拟考试**：任意已发布试卷一键开考，120 分钟倒计时自动交卷，自评式判分（本题无选择题题库，逐题自评答对/答错/未作答），交卷出成绩单：总分/正确率/按题型与知识点得分率，并展开每题的答案与解析
- 📝 个人笔记：每题一条（支持 Markdown 与公式），“我的笔记”分页汇总
- 📅 每日一题：日期种子随机，当天全站同一题、次日更换
- 📤 学习数据导出：作答 / 收藏 / 错题 / 笔记一键导出 CSV（Excel 友好）
- 🛠️ 基于 openpyxl 工作簿的一键导入流程（试导入 dry-run + 正式导入 + 校验）
- 🧪 内置 212 项自动化测试（Web 端模型/视图/导入/admin/学习功能全覆盖，含复习排期、模拟考试、组卷与新统计）与浏览器公式渲染检查脚本
- 📱 配套微信小程序端，题库数据内置、离线可用

## 技术栈

- Python 3.11+，Django 5.2，SQLite（单文件数据库）
- KaTeX 0.18 + Bootstrap 5（前端）
- openpyxl（题库导入）、Markdown（题干/解析渲染）
- Node.js 20+（仅开发机导入题库时校验公式、跑渲染检查脚本用；站点运行无需 Node/npm）

## 目录结构

```
全国大学生18届/
├── manage.py              # Django 管理入口
├── db.sqlite3             # 数据库（含全部题目，已被 git 忽略）
├── config/                # 项目配置（settings 读取 .env）
├── question_bank/         # 题库主应用（模型、视图、导入命令）
├── accounts/              # 用户模块
├── 微信小程序/             # 微信小程序端（页面、组件、题库数据；已被 git 忽略，不随仓库分发）
├── scripts/               # 公式渲染 / 检查脚本（render-*.mjs、test-*.mjs）
├── data/
│   ├── import/            # 各届导入工作簿（questions.xlsx、source_inventory.xlsx）
│   ├── review/            # 各届校验脚本、数据库备份、公式检查脚本
│   └── templates/         # 工作簿模板
├── media/papers/          # 各届试卷 PDF（edition-01 ~ edition-17）
├── static/                # 源码静态资源 + 内置 vendor（Bootstrap/KaTeX 副本）
├── staticfiles/           # collectstatic 产物
├── deploy/                # 生产部署配置（Caddy、systemd、备份脚本）
├── docs/deploy-checklist.md  # 公网部署安全清单（环境变量/限流/CSP/备份演练）
├── docs/                  # 文档（收件人指南、优化方案等）
├── start_bank_site.bat    # 一键启动（自动建 venv/装依赖/迁移并开浏览器）
├── create_admin_account.bat # 创建后台管理员
├── make_release.ps1       # 制作发行 zip 包
└── .env.example           # 环境变量示例
```

## 首次部署（个人电脑 / Windows）

### 方式零：双击 exe（收件人零依赖，推荐）

发行包里的 `数学竞赛题库.exe` 无需安装 Python——双击先显示**启动画面**（解开内置资源），随后自动弹出浏览器进入登录页；程序**不显示终端窗口**，控制台输出写入数据目录的 `bank.log`。数据（`db.sqlite3`、`media/`、日志）默认固定存放在 `%LOCALAPPDATA%\MathQuestionBank`，**不随 exe 位置变化**——换文件夹、挪动/删除 exe 都不丢数据，从压缩包里直接双击运行也不会把数据写进临时目录；exe 旁放一个空文件 `portable.flag` 可改为 exe 同目录存储（U 盘便携），旧版 exe 目录里的数据会在新版首次启动时自动搬迁。端口 8000–8009 自动挑空闲的；重复双击只会把浏览器带到已在运行的那个实例。网页「我的」页右下角有 **📂 打开数据文件夹** 与 **退出桌面版**（干净地停止服务，数据保留）。重新打包命令见《使用者必看.md》文末打包者备注。

### 方式一：一键启动（bat，适合发了源码让别人跑）

收件人只需两步（发行包根目录的《使用者必看.md》有完整说明）：

1. 安装 Python 3.11+，勾选 "Add python.exe to PATH"；
2. 双击 `start_bank_site.bat` —— 首次自动建 venv、装依赖、初始化数据库并打开浏览器；之后每次双击即启。

可选：双击 `create_admin_account.bat` 创建后台管理员账号。

### 方式二：手动命令行

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

浏览器打开 <http://127.0.0.1:8000/papers/> 即可使用。

> **访问门禁**：站点默认全站需登录——打开网站先到登录页，注册/登录后才能浏览；退出登录后回到登录页。管理员账号仍通过 `create_admin_account.bat` 创建。

> Bootstrap 与 KaTeX 已内置在 `static/vendor/` 中，**无需 npm install**；前端资源变更时才需要 `python manage.py collectstatic`（生产模式）。

> 题库数据（`db.sqlite3` 与 `media/`）**不随 git 仓库分发**（版权考量，仅含程序源码）。从压缩包/他人处获得本项目时，数据文件已就位，migrate 之后即可使用；从 git 克隆全新初始化时需先取得数据文件（或用导入命令从 `data/import/` 工作簿导入，该工作簿同样不入库，需自行获取）。

## 日常使用

- 启动：`python manage.py runserver 127.0.0.1:8000`
- 浏览：<http://127.0.0.1:8000/papers/> 试卷列表，点击进入试卷可查看题目、解析并下载 PDF 或打印整卷
- 学习：试卷页“连续刷本卷”进入练习模式，**“⏱ 模拟考试”**整卷自考评卷；首页“每日一题”直接开练，登录后首页显示**今日任务**（到期复习 + 智能组卷）；顶部“我的”查看统计/笔记/导出
- 测试：`python manage.py test`（当前 212 项用例应全部通过；导入相关用例依赖 Node，需 node 在 PATH 中）
- 备份：直接复制 `db.sqlite3` 与 `media/` 目录即可（推荐每天/每次导入前备份）

## 导入新一届题库

以第 17 届为例，完整流程如下：

1. **准备试卷 PDF**：将初赛/决赛（A/B）PDF 放入

```
media/papers/edition-17/preliminary.pdf
media/papers/edition-17/preliminary-b.pdf
media/papers/edition-17/final.pdf
media/papers/edition-17/final-b.pdf
```

2. **生成导入工作簿**：参考 `data/review/edition-17/build_import_workbooks.py`（A 类）与 `build_import_workbooks_b.py`（B 类），运行后生成：

```
data/import/edition-17/questions.xlsx
data/import/edition-17/source_inventory.xlsx
data/import/edition-17-b/…
```

3. **试导入**：

```powershell
python manage.py import_question_bank `
  --inventory data\import\edition-17\source_inventory.xlsx `
  --questions data\import\edition-17\questions.xlsx --dry-run
```

4. **正式导入**（去掉 `--dry-run`）：

```powershell
python manage.py import_question_bank `
  --inventory data\import\edition-17\source_inventory.xlsx `
  --questions data\import\edition-17\questions.xlsx
```

5. **发布**：导入后试卷与题目处于 `reviewed` 状态，需要置为 `published` 才能在前台显示：

```powershell
.venv\Scripts\python.exe -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); import django; django.setup(); from question_bank.models import Paper, Question; Paper.objects.filter(edition=17).update(status='published'); Question.objects.filter(paper__edition=17).update(status='published')"
```

6. **验证**：跑测试，并用浏览器逐题检查公式渲染：

```powershell
python manage.py test question_bank
node data\review\edition-17\browser_math_check.cjs   # 需先启动站点
```

## 浏览器公式检查（可选）

`data/review/edition-XX/browser_math_check.cjs` 会打开每一道已发布题目，确认 KaTeX 正常渲染且页面无裸 `$` 残留。使用前需要：

```powershell
npm install -D playwright
npx playwright install chromium
```

然后启动站点并运行脚本（当前第 17 届：26 题、786 个公式，0 错误）。

## 开机自启（Windows）

**方式一：启动文件夹**（简单）

1. 在项目根新建 `start.bat`：

```bat
@echo off
cd /d C:\你的项目路径\全国大学生18届
start "" .venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

2. 按 `Win+R` 输入 `shell:startup`，把 `start.bat` 的快捷方式放进去。

**方式二：任务计划程序**（推荐）

1. 任务计划程序 → 创建任务；
2. 触发器：登录时；操作：启动程序，程序填 `.venv\Scripts\python.exe`，参数填 `manage.py runserver 127.0.0.1:8000`，起始于项目根目录；
3. 勾选“不管用户是否登录都要运行”可隐藏窗口。

## 局域网 / 生产部署（可选）

- **局域网访问**：`runserver 0.0.0.0:8000`，并把 `.env` 中 `DJANGO_ALLOWED_HOSTS` 加上本机局域网 IP。
- **Windows 生产**：`pip install waitress`，用 `waitress-serve --listen=0.0.0.0:8000 config.wsgi:application` 常驻。
- **Linux 生产**：`requirements.txt` 已含 gunicorn，可用 `gunicorn config.wsgi:application -b 0.0.0.0:8000`；关闭 DEBUG 时必须设置 `DJANGO_SECRET_KEY`（非 dev-only-key）。

## 数据说明

- 第 1–14 届仅有非数学类统一试卷；第 15 届初赛起分 A/B 类；第 16–17 届初赛与决赛均分 A/B 类。
- 第 17 届决赛 PDF 由公众号图片生成，非官方排版版本，其余各届均为官方/扫描 PDF。
- 数据库与媒体文件均被 git 忽略，代码仓库只包含程序源码；换机迁移时需一并拷贝 `db.sqlite3` 与 `media/`。

## 后续工程优化

系统级优化方案（安全基线、双端数据同步、导入管线、可观测性等）见 [docs/optimization-plan.md](docs/optimization-plan.md)。
