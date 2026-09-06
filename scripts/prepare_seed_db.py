#!/usr/bin/env python
"""生成发布用种子数据库：从项目库复制一份，剔除所有真实用户数据。

用法（在项目根目录）：
    .venv/Scripts/python.exe scripts/prepare_seed_db.py

产出 packaging_tmp/db.sqlite3，只保留题库内容（试卷/题目/知识点等），
清空：账号、会话、作答记录、收藏、错题、笔记、练习进度、考试记录等。

只在 packaging_tmp 下操作副本，绝不修改项目根目录的 db.sqlite3。
"""
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "db.sqlite3"
DST_DIR = ROOT / "packaging_tmp"
DST = DST_DIR / "db.sqlite3"


def main() -> int:
    if not SRC.exists():
        print(f"找不到源库：{SRC}")
        return 1
    DST_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC, DST)  # 覆盖旧种子，保证与打包时一致

    conn = sqlite3.connect(DST)
    try:
        cur = conn.cursor()
        wiped = 0
        # 用户数据表（及失效会话）逐条清空；以下每条 SQL 均为不可变字面量，
        # 旧库缺表时视为跳过
        try:
            cur.execute("DELETE FROM accounts_user")
            wiped += 1
        except sqlite3.OperationalError:
            pass
        # 题目的审核人是唯一"随用户删除"后残留的悬空外键（SET_NULL 字段）。
        # 不清掉的话，Django 5.2 在应用涉及表重建的迁移时会做全库外键校验，
        # 种子库第一次迁移就会报 invalid foreign key。
        try:
            cur.execute("UPDATE question_bank_question SET reviewed_by_id = NULL")
            wiped += 1
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("DELETE FROM accounts_user_groups")
            wiped += 1
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("DELETE FROM accounts_user_user_permissions")
            wiped += 1
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("DELETE FROM question_bank_answerrecord")
            wiped += 1
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("DELETE FROM question_bank_favorite")
            wiped += 1
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("DELETE FROM question_bank_note")
            wiped += 1
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("DELETE FROM question_bank_wrongquestion")
            wiped += 1
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("DELETE FROM question_bank_practiceprogress")
            wiped += 1
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("DELETE FROM question_bank_examattempt")
            wiped += 1
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("DELETE FROM question_bank_examanswer")
            wiped += 1
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("DELETE FROM django_session")
            wiped += 1
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("DELETE FROM django_admin_log")
            wiped += 1
        except sqlite3.OperationalError:
            pass
        conn.commit()
        print(f"  已清空 {wiped} 张用户数据表（不存在的表自动跳过）")
        print(f"\n种子库已生成：{DST}")
        print("保留内容：题库数据（试卷/题目/知识点）；用户数据已全部清空。")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())