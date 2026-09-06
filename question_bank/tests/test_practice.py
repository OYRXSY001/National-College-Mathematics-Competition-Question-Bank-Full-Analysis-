"""P0–P2 学习功能测试：练习模式、错题本掌握流、统计、笔记、打印、导出、每日一题。"""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from question_bank.models import (
    AnswerRecord,
    Favorite,
    KnowledgePoint,
    Note,
    Paper,
    PracticeProgress,
    Question,
    QuestionKnowledgePoint,
    WrongQuestion,
)


class LearningBaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("learner", password="pass-12345")
        cls.reviewer = get_user_model().objects.create_user("learning-reviewer")
        cls.paper = Paper.objects.create(
            edition=17,
            stage="preliminary",
            original_category_label="非数学A类",
            title="第17届非数学A类初赛",
            status="published",
        )
        cls.knowledge = KnowledgePoint.objects.create(
            name="函数极限", slug="function-limit", subject="calculus"
        )
        cls.questions = []
        for number in (1, 2, 3):
            question = Question.objects.create(
                paper=cls.paper,
                question_no=str(number),
                sort_order=number,
                question_type="calculation",
                stem_md=f"计算 {number}。",
                answer_md=f"答案{number}",
                solution_md=f"解析{number}",
                source_page=number,
                text_checked=True,
                formula_checked=True,
                solution_checked=True,
                reviewed_by=cls.reviewer,
                reviewed_at=timezone.now(),
                status=Question.Status.REVIEWED,
            )
            QuestionKnowledgePoint.objects.create(
                question=question, knowledge_point=cls.knowledge, is_primary=True
            )
            question.status = Question.Status.PUBLISHED
            question.save()
            cls.questions.append(question)

    def setUp(self):
        self.client.force_login(self.user)


class PracticeTests(LearningBaseTests):
    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("practice"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_paper_scope_presents_questions_in_order(self):
        response = self.client.get(
            reverse("practice"), {"scope": f"paper:{self.paper.pk}"}
        )

        self.assertContains(response, "第17届非数学A类初赛")
        self.assertContains(response, "第 1 / 3 题")
        # 按 sort_order 出第一题
        self.assertContains(response, self.questions[0].stem_md)

    def test_knowledge_scope_filters_questions(self):
        response = self.client.get(
            reverse("practice"), {"scope": f"knowledge:{self.knowledge.slug}"}
        )

        self.assertContains(response, "第 1 / 3 题")

    def test_all_scope_lists_every_published_question(self):
        response = self.client.get(reverse("practice"), {"scope": "all"})

        self.assertContains(response, "第 1 / 3 题")

    def test_wrong_answer_records_and_creates_wrong_question(self):
        response = self.client.post(
            reverse("practice-verdict"),
            {"qid": self.questions[0].pk, "result": "wrong"},
        )

        self.assertEqual(response.status_code, 302)
        record = AnswerRecord.objects.get(
            user=self.user, question=self.questions[0]
        )
        self.assertFalse(record.is_correct)
        wrong = WrongQuestion.objects.get(
            user=self.user, question=self.questions[0]
        )
        self.assertEqual(wrong.wrong_count, 1)
        self.assertIsNotNone(wrong.last_wrong_at)
        self.assertIsNone(wrong.mastered_at)
        # 回到刚作答的题展示结果（"下一题"按钮在结果页上）
        self.assertIn(f"qid={self.questions[0].pk}", response.url)
        self.assertIn("outcome=wrong", response.url)

    def test_correct_answer_writes_record_without_wrong_book(self):
        response = self.client.post(
            reverse("practice-verdict"),
            {"qid": self.questions[0].pk, "result": "correct"},
        )

        self.assertEqual(response.status_code, 302)
        record = AnswerRecord.objects.get(
            user=self.user, question=self.questions[0]
        )
        self.assertTrue(record.is_correct)
        self.assertFalse(
            WrongQuestion.objects.filter(
                user=self.user, question=self.questions[0]
            ).exists()
        )

    def test_repeated_wrong_answers_accumulate_count(self):
        for _ in range(3):
            self.client.post(
                reverse("practice-verdict"),
                {"qid": self.questions[0].pk, "result": "wrong"},
            )

        wrong = WrongQuestion.objects.get(
            user=self.user, question=self.questions[0]
        )
        self.assertEqual(wrong.wrong_count, 3)
        self.assertEqual(
            AnswerRecord.objects.filter(
                user=self.user, question=self.questions[0], is_correct=False
            ).count(),
            3,
        )

    def test_skip_writes_no_answer_record(self):
        response = self.client.post(
            reverse("practice-verdict"),
            {"qid": self.questions[0].pk, "result": "skip"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f"qid={self.questions[0].pk}", response.url)
        self.assertIn("outcome=skip", response.url)
        self.assertFalse(
            AnswerRecord.objects.filter(
                user=self.user, question=self.questions[0]
            ).exists()
        )

    def test_outcome_page_shows_answered_question_and_next_has_form(self):
        """P0 回归：结果页显示刚作答的题（而非带着结果跳下一题，
        导致下一题答案被提前展开且没有作答表单）。"""
        scope = f"paper:{self.paper.pk}"
        response = self.client.post(
            reverse("practice-verdict"),
            {"qid": self.questions[0].pk, "scope": scope, "result": "wrong"},
        )

        result_page = self.client.get(response.url)
        # 显示的是刚答的第 1 题及判分横幅
        self.assertContains(result_page, "计算 1。")
        self.assertContains(result_page, "已记入错题本")
        self.assertContains(result_page, "下一题")
        # 下一题页面：无 outcome，作答表单回归
        next_page = self.client.get(
            reverse("practice"),
            {"qid": self.questions[1].pk, "scope": scope},
        )
        self.assertContains(next_page, "计算 2。")
        self.assertContains(next_page, "答对了")

    def test_book_scope_practices_only_unmastered_wrong_questions(self):
        for question in self.questions[:2]:
            WrongQuestion.objects.create(user=self.user, question=question)
        wrong = WrongQuestion.objects.get(
            user=self.user, question=self.questions[1]
        )
        wrong.mastered_at = timezone.now()
        wrong.save()

        response = self.client.get(reverse("practice"), {"scope": "book"})

        self.assertContains(response, "第 1 / 1 题")
        self.assertContains(response, self.questions[0].stem_md)
        self.assertNotContains(response, self.questions[1].stem_md)

    def test_practice_page_renders_book_question(self):
        WrongQuestion.objects.create(user=self.user, question=self.questions[0])

        response = self.client.get(reverse("practice"), {"scope": "book"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.questions[0].stem_md)


class WrongQuestionFlowTests(LearningBaseTests):
    def test_wrong_list_defaults_to_unmastered_only(self):
        WrongQuestion.objects.create(user=self.user, question=self.questions[0])
        mastered = WrongQuestion.objects.create(
            user=self.user, question=self.questions[1]
        )
        mastered.mastered_at = timezone.now()
        mastered.save()

        response = self.client.get(reverse("wrong-questions"))

        self.assertContains(response, self.questions[0].stem_md)
        self.assertNotContains(response, self.questions[1].stem_md)

    def test_mastered_filter_shows_only_mastered(self):
        mastered = WrongQuestion.objects.create(
            user=self.user, question=self.questions[1]
        )
        mastered.mastered_at = timezone.now()
        mastered.save()

        response = self.client.get(reverse("wrong-questions"), {"mastered": "1"})

        self.assertContains(response, self.questions[1].stem_md)
        self.assertNotContains(response, self.questions[0].stem_md)

    def test_toggle_mastered_marks_and_unmarks(self):
        WrongQuestion.objects.create(user=self.user, question=self.questions[0])
        url = reverse("wrong-toggle-mastered", args=[self.questions[0].pk])

        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        wrong = WrongQuestion.objects.get(
            user=self.user, question=self.questions[0]
        )
        self.assertIsNotNone(wrong.mastered_at)

        self.client.post(url)
        wrong.refresh_from_db()
        self.assertIsNone(wrong.mastered_at)

    def test_mastering_question_keeps_answer_history(self):
        for _ in range(2):
            self.client.post(
                reverse("practice-verdict"),
                {"qid": self.questions[0].pk, "result": "wrong"},
            )
        wrong = WrongQuestion.objects.get(
            user=self.user, question=self.questions[0]
        )
        wrong.mastered_at = timezone.now()
        wrong.save()

        self.assertEqual(
            AnswerRecord.objects.filter(
                user=self.user, question=self.questions[0], is_correct=False
            ).count(),
            2,
        )


class MeStatsTests(LearningBaseTests):
    def test_stat_page_aggregates_totals(self):
        AnswerRecord.objects.create(
            user=self.user, question=self.questions[0], is_correct=True
        )
        AnswerRecord.objects.create(
            user=self.user, question=self.questions[0], is_correct=True
        )
        AnswerRecord.objects.create(
            user=self.user, question=self.questions[1], is_correct=False
        )
        WrongQuestion.objects.create(user=self.user, question=self.questions[1])

        response = self.client.get(reverse("me"))

        self.assertContains(response, "我的学习统计")
        self.assertContains(response, "3")  # 累计作答
        self.assertContains(response, "67")  # 2/3 ≈ 67%
        self.assertContains(response, "1")  # 错题待复习

    def test_me_weak_points_only_list_primary_incorrect_knowledge(self):
        self.client.post(
            reverse("practice-verdict"),
            {"qid": self.questions[0].pk, "result": "wrong"},
        )
        self.client.post(
            reverse("practice-verdict"),
            {"qid": self.questions[1].pk, "result": "correct"},
        )

        response = self.client.get(reverse("me"))

        self.assertContains(response, "函数极限")
        self.assertContains(response, "1 次答错")


class NoteTests(LearningBaseTests):
    def test_save_note_then_show_on_notes_page(self):
        url = reverse("note-save", args=[self.questions[0].pk])
        response = self.client.post(url, {"body": "夹逼定理的思路"})

        self.assertEqual(response.status_code, 302)
        note = Note.objects.get(
            user=self.user, question=self.questions[0]
        )
        self.assertEqual(note.body, "夹逼定理的思路")

        notes_page = self.client.get(reverse("me-notes"))
        self.assertContains(notes_page, "夹逼定理的思路")
        self.assertContains(notes_page, self.questions[0].stem_md)

    def test_save_note_updates_existing_body(self):
        uri = reverse("note-save", args=[self.questions[0].pk])
        self.client.post(uri, {"body": "第一版"})
        self.client.post(uri, {"body": "第二版"})

        self.assertEqual(
            Note.objects.get(user=self.user, question=self.questions[0]).body,
            "第二版",
        )

    def test_empty_body_or_clear_deletes_note(self):
        url = reverse("note-save", args=[self.questions[0].pk])
        self.client.post(url, {"body": "内容"})
        self.client.post(url, {"body": "  "})
        self.assertFalse(
            Note.objects.filter(user=self.user, question=self.questions[0]).exists()
        )
        self.client.post(url, {"body": "内容"})
        self.client.post(url, {"clear": "1"})
        self.assertFalse(
            Note.objects.filter(user=self.user, question=self.questions[0]).exists()
        )

    def test_user_cannot_see_others_notes(self):
        other = get_user_model().objects.create_user("note-other")
        Note.objects.create(user=other, question=self.questions[0], body="别人笔记")

        response = self.client.get(reverse("me-notes"))

        self.assertNotContains(response, "别人笔记")

    def test_question_card_shows_note_badge(self):
        Note.objects.create(
            user=self.user, question=self.questions[0], body="记过了"
        )

        response = self.client.get(
            reverse("question-detail", args=[self.questions[0].pk])
        )

        self.assertContains(response, "已记笔记")
        self.assertContains(response, "记过了")
        self.assertContains(response, "note-editor")


class PrintTests(LearningBaseTests):
    def test_print_without_answers_hides_solutions(self):
        response = self.client.get(
            reverse("paper-print", args=[self.paper.pk])
        )

        self.assertContains(response, "第1题")
        self.assertContains(response, self.questions[0].stem_md)
        self.assertNotContains(response, self.questions[0].solution_md)
        self.assertContains(response, "answer-space")

    def test_print_with_answers_flag_shows_solutions(self):
        response = self.client.get(
            reverse("paper-print", args=[self.paper.pk]), {"answers": "1"}
        )

        self.assertContains(response, self.questions[0].answer_md)
        self.assertContains(response, self.questions[0].solution_md)

    def test_print_hides_draft_paper(self):
        draft = Paper.objects.create(
            edition=15,
            stage="preliminary",
            original_category_label="非数学A类",
            title="草稿试卷",
        )
        response = self.client.get(reverse("paper-print", args=[draft.pk]))

        self.assertEqual(response.status_code, 404)


class ExportTests(LearningBaseTests):
    def test_export_contains_header_and_rows_per_record(self):
        AnswerRecord.objects.create(
            user=self.user, question=self.questions[0], is_correct=False
        )
        Favorite.objects.create(user=self.user, question=self.questions[1])
        WrongQuestion.objects.create(user=self.user, question=self.questions[2])
        Note.objects.create(
            user=self.user, question=self.questions[0], body="我的笔记内容"
        )

        response = self.client.get(reverse("me-export"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8-sig")
        lines = [line for line in content.splitlines() if line.strip()]
        self.assertEqual(lines[0], "类型,届数,试卷,题号,题型,知识点,内容,时间")
        self.assertEqual(len(lines), 5)  # 表头 + 4 条记录(作答/收藏/错题/笔记)
        self.assertIn("作答", content)
        self.assertIn("收藏", content)
        self.assertIn("错题", content)
        self.assertIn("笔记", content)
        self.assertIn("我的笔记内容", content)
        self.assertIn("函数极限", content)


class DailyQuestionTests(LearningBaseTests):
    @staticmethod
    def _qid_of(response):
        import re

        match = re.search(rb"\?qid=(\d+)", response.content)
        return int(match.group(1)) if match else None

    def test_daily_question_is_stable_within_a_day(self):
        with mock.patch(
            "question_bank.views.timezone.localdate", return_value=date(2026, 9, 3)
        ):
            first = self.client.get(reverse("home"))
            second = self.client.get(reverse("home"))

        self.assertContains(first, "每日一题")
        self.assertContains(first, "去做这一题")
        self.assertIsNotNone(self._qid_of(first))
        self.assertEqual(self._qid_of(first), self._qid_of(second))

    def test_daily_question_changes_next_day(self):
        with mock.patch(
            "question_bank.views.timezone.localdate", return_value=date(2026, 9, 3)
        ):
            first = self.client.get(reverse("home"))
        with mock.patch(
            "question_bank.views.timezone.localdate", return_value=date(2026, 9, 5)
        ):
            second = self.client.get(reverse("home"))

        self.assertNotEqual(self._qid_of(first), self._qid_of(second))

    def test_daily_question_only_from_published_questions(self):
        draft = Paper.objects.create(
            edition=14,
            stage="final",
            original_category_label="非数学A类",
            title="未发布卷",
        )
        draft_question = Question.objects.create(
            paper=draft,
            question_no="9",
            sort_order=9,
            question_type="calculation",
            stem_md="草稿题目不应出现",
            solution_md="草稿解析",
            source_page=1,
            text_checked=True,
            formula_checked=True,
            solution_checked=True,
            reviewed_by=self.reviewer,
            reviewed_at=timezone.now(),
            status=Question.Status.REVIEWED,
        )
        QuestionKnowledgePoint.objects.create(
            question=draft_question, knowledge_point=self.knowledge, is_primary=True
        )
        draft_question.status = Question.Status.PUBLISHED
        draft_question.save()

        with mock.patch(
            "question_bank.views.timezone.localdate", return_value=date(2026, 9, 3)
        ):
            response = self.client.get(reverse("home"))

        self.assertNotContains(response, "草稿题目")


class ReviewScheduleTests(LearningBaseTests):
    def test_wrong_answer_schedules_review_tomorrow(self):
        self.client.post(
            reverse("practice-verdict"),
            {"qid": self.questions[0].pk, "result": "wrong"},
        )

        wrong = WrongQuestion.objects.get(
            user=self.user, question=self.questions[0]
        )
        self.assertEqual(
            wrong.next_review_at, timezone.localdate() + timezone.timedelta(days=1)
        )
        self.assertEqual(wrong.review_stage, 0)

    def test_review_scope_contains_only_due_questions(self):
        due = WrongQuestion.objects.create(
            user=self.user,
            question=self.questions[0],
            next_review_at=timezone.localdate(),
        )
        not_due = WrongQuestion.objects.create(
            user=self.user,
            question=self.questions[1],
            next_review_at=timezone.localdate() + timezone.timedelta(days=3),
        )

        response = self.client.get(reverse("practice"), {"scope": "review"})

        self.assertContains(response, self.questions[0].stem_md)
        self.assertNotContains(response, self.questions[1].stem_md)
        # 未到期的排期复习不打扰
        self.assertTrue(
            WrongQuestion.objects.filter(pk=not_due.pk).exists()
        )

    def test_review_correct_answer_advances_stage(self):
        WrongQuestion.objects.create(
            user=self.user,
            question=self.questions[0],
            next_review_at=timezone.localdate(),
        )

        response = self.client.post(
            reverse("practice-verdict"),
            {
                "qid": self.questions[0].pk,
                "scope": "review",
                "result": "correct",
            },
        )

        self.assertEqual(response.status_code, 302)
        wrong = WrongQuestion.objects.get(
            user=self.user, question=self.questions[0]
        )
        self.assertEqual(wrong.review_stage, 1)
        self.assertEqual(
            wrong.next_review_at,
            timezone.localdate() + timezone.timedelta(days=3),
        )
        self.assertIsNone(wrong.mastered_at)

    def test_review_mastered_after_four_correct_answers(self):
        WrongQuestion.objects.create(
            user=self.user,
            question=self.questions[0],
            next_review_at=timezone.localdate(),
            review_stage=3,
        )
        for _ in range(4):
            self.client.post(
                reverse("practice-verdict"),
                {
                    "qid": self.questions[0].pk,
                    "scope": "review",
                    "result": "correct",
                },
            )

        wrong = WrongQuestion.objects.get(
            user=self.user, question=self.questions[0]
        )
        self.assertEqual(wrong.review_stage, 4)
        self.assertIsNotNone(wrong.mastered_at)
        self.assertIsNone(wrong.next_review_at)

    def test_review_wrong_answer_resets_stage(self):
        WrongQuestion.objects.create(
            user=self.user,
            question=self.questions[0],
            next_review_at=timezone.localdate(),
            review_stage=2,
        )
        self.client.post(
            reverse("practice-verdict"),
            {
                "qid": self.questions[0].pk,
                "scope": "review",
                "result": "wrong",
            },
        )

        wrong = WrongQuestion.objects.get(
            user=self.user, question=self.questions[0]
        )
        self.assertEqual(wrong.review_stage, 0)
        self.assertEqual(
            wrong.next_review_at,
            timezone.localdate() + timezone.timedelta(days=1),
        )

    def test_mastered_question_wrong_again_reenters_review_queue(self):
        """已掌握的题再答错：清除掌握标记、回到第 0 档、明天复习。"""
        WrongQuestion.objects.create(
            user=self.user,
            question=self.questions[0],
            mastered_at=timezone.now(),
            review_stage=4,
        )
        self.client.post(
            reverse("practice-verdict"),
            {"qid": self.questions[0].pk, "result": "wrong"},
        )

        wrong = WrongQuestion.objects.get(
            user=self.user, question=self.questions[0]
        )
        self.assertIsNone(wrong.mastered_at)
        self.assertEqual(wrong.review_stage, 0)
        self.assertEqual(
            wrong.next_review_at,
            timezone.localdate() + timezone.timedelta(days=1),
        )


class WeakQuizTests(LearningBaseTests):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # 弱知识点：函数极限 → 3 次答错；另一知识点答对，不应入组卷
        for question in cls.questions:
            AnswerRecord.objects.create(
                user=cls.user, question=question, is_correct=False
            )
        cls.strong = KnowledgePoint.objects.create(
            name="多元积分", slug="multi-integral", subject="calculus"
        )
        strong_question = Question.objects.create(
            paper=cls.paper,
            question_no="9",
            sort_order=9,
            question_type="calculation",
            stem_md="强项题目",
            answer_md="答案",
            solution_md="解析",
            source_page=9,
            text_checked=True,
            formula_checked=True,
            solution_checked=True,
            reviewed_by=cls.reviewer,
            reviewed_at=timezone.now(),
            status=Question.Status.REVIEWED,
        )
        QuestionKnowledgePoint.objects.create(
            question=strong_question,
            knowledge_point=cls.strong,
            is_primary=True,
        )
        strong_question.status = Question.Status.PUBLISHED
        strong_question.save()
        cls.strong_question = strong_question

    def test_weak_scope_contains_only_weak_knowledge_questions(self):
        response = self.client.get(reverse("practice"), {"scope": "weak"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "智能组卷 · 薄弱巩固")
        self.assertContains(response, self.questions[0].stem_md)
        self.assertNotContains(response, self.strong_question.stem_md)

    def test_weak_scope_limited_to_15_questions(self):
        # 再补 15 道弱知识点题目（编号避开已有题），超过 15 上限应被抽样截断
        for number in range(20, 35):
            extra = Question.objects.create(
                paper=self.paper,
                question_no=str(number),
                sort_order=number,
                question_type="calculation",
                stem_md=f"第 {number} 题",
                answer_md="答案",
                solution_md="解析",
                source_page=number,
                text_checked=True,
                formula_checked=True,
                solution_checked=True,
                reviewed_by=self.reviewer,
                reviewed_at=timezone.now(),
                status=Question.Status.REVIEWED,
            )
            QuestionKnowledgePoint.objects.create(
                question=extra, knowledge_point=self.knowledge, is_primary=True
            )
            extra.status = Question.Status.PUBLISHED
            extra.save()

        response = self.client.get(reverse("practice"), {"scope": "weak"})

        # 练习页一题一屏，总题数体现在进度条：被抽样截断到 15 题
        self.assertContains(response, "第 1 / 15 题")

    def test_weak_sample_stable_within_a_day(self):
        """抽样必须跨请求稳定：判分 GET/POST 各自求值若重抽，
        当前题可能不在样本里导致提前完成、进度存不上。"""
        from question_bank.views import _weak_scope_ids

        for number in range(20, 40):
            extra = Question.objects.create(
                paper=self.paper,
                question_no=str(number),
                sort_order=number,
                question_type="calculation",
                stem_md=f"第 {number} 题",
                answer_md="答案",
                solution_md="解析",
                source_page=number,
                text_checked=True,
                formula_checked=True,
                solution_checked=True,
                reviewed_by=self.reviewer,
                reviewed_at=timezone.now(),
                status=Question.Status.REVIEWED,
            )
            QuestionKnowledgePoint.objects.create(
                question=extra, knowledge_point=self.knowledge, is_primary=True
            )
            extra.status = Question.Status.PUBLISHED
            extra.save()

        first = _weak_scope_ids(self.user)
        second = _weak_scope_ids(self.user)

        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 15)

    def test_weak_scope_empty_when_no_wrong_records(self):
        for record in AnswerRecord.objects.filter(user=self.user):
            record.delete()

        response = self.client.get(reverse("practice"), {"scope": "weak"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "当前范围暂无题目")


class HomeTaskPanelTests(LearningBaseTests):
    def test_home_shows_tasks_panel_when_logged_in(self):
        answer = AnswerRecord.objects.create(
            user=self.user, question=self.questions[0], is_correct=False
        )
        WrongQuestion.objects.create(
            user=self.user,
            question=self.questions[0],
            next_review_at=timezone.localdate(),
        )
        PracticeProgress.objects.create(
            user=self.user, scope="paper:{pk}".format(pk=self.paper.pk), position=1
        )

        response = self.client.get(reverse("home"))

        self.assertContains(response, "今日任务")
        self.assertContains(response, "1 题待复习")
        self.assertContains(response, "继续上次练习")
        self.assertContains(response, "智能组卷")

    def test_home_hides_tasks_panel_for_anonymous(self):
        # 站点全局门禁：匿名访问一律 302 到登录页，根本看不到首页面板
        self.client.logout()
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_home_due_count_ignores_unpublished_questions(self):
        """待复习徽标与 review 范围同款过滤：题目下架后入口数字不虚报。"""
        draft = Question.objects.create(
            paper=self.paper,
            question_no="99",
            sort_order=99,
            question_type="calculation",
            stem_md="下架的题",
            answer_md="答案",
            solution_md="解析",
            source_page=99,
            text_checked=True,
            formula_checked=True,
            solution_checked=True,
            reviewed_by=self.reviewer,
            reviewed_at=timezone.now(),
            status=Question.Status.REVIEWED,
        )
        WrongQuestion.objects.create(
            user=self.user,
            question=draft,
            next_review_at=timezone.localdate(),
        )

        response = self.client.get(reverse("home"))

        self.assertNotContains(response, "1 题待复习")


class PracticeProgressTests(LearningBaseTests):
    def test_answering_saves_progress_position(self):
        # 稳定范围（paper）答完首题应存断点
        scope = f"paper:{self.paper.pk}"
        self.client.post(
            reverse("practice-verdict"),
            {"qid": self.questions[0].pk, "scope": scope, "result": "correct"},
        )

        progress = PracticeProgress.objects.get(user=self.user, scope=scope)
        self.assertEqual(progress.position, 1)

    def test_dynamic_scopes_do_not_save_progress(self):
        # review/book 的题集随作答动态增删，恢复 position 会跳题，不存断点
        now = timezone.now()
        WrongQuestion.objects.create(
            user=self.user, question=self.questions[0], last_wrong_at=now
        )
        self.client.post(
            reverse("practice-verdict"),
            {"qid": self.questions[0].pk, "scope": "book", "result": "correct"},
        )
        self.assertFalse(
            PracticeProgress.objects.filter(user=self.user, scope="book").exists()
        )

    def test_practice_fresh_clears_saved_progress(self):
        scope = f"paper:{self.paper.pk}"
        PracticeProgress.objects.create(user=self.user, scope=scope, position=1)
        self.client.get(reverse("practice"), {"scope": scope, "fresh": "1"})

        self.assertFalse(
            PracticeProgress.objects.filter(user=self.user, scope=scope).exists()
        )

    def test_practice_resumes_from_saved_position(self):
        scope = f"paper:{self.paper.pk}"
        PracticeProgress.objects.create(user=self.user, scope=scope, position=1)
        response = self.client.get(reverse("practice"), {"scope": scope})

        self.assertContains(response, "已从上次进度继续")
        self.assertContains(response, self.questions[1].stem_md)

    def test_practice_fresh_starts_from_beginning(self):
        scope = f"paper:{self.paper.pk}"
        PracticeProgress.objects.create(user=self.user, scope=scope, position=1)
        response = self.client.get(
            reverse("practice"), {"scope": scope, "fresh": "1"}
        )

        self.assertNotContains(response, "已从上次进度继续")
        self.assertContains(response, self.questions[0].stem_md)

    def test_finished_scope_clears_progress(self):
        scope = f"paper:{self.paper.pk}"
        for question in self.questions:
            self.client.post(
                reverse("practice-verdict"),
                {"qid": question.pk, "scope": scope, "result": "correct"},
            )

        self.assertFalse(
            PracticeProgress.objects.filter(user=self.user, scope=scope).exists()
        )


class PracticeShortcutTests(LearningBaseTests):
    def test_practice_page_mentions_keyboard_shortcuts(self):
        response = self.client.get(
            reverse("practice"), {"scope": f"paper:{self.paper.pk}"}
        )

        self.assertContains(response, "<kbd>1</kbd>")
        self.assertContains(response, "<kbd>2</kbd>")
        self.assertContains(response, "<kbd>3</kbd>")
        self.assertContains(response, "practice.js")


class VerdictSnapshotTests(LearningBaseTests):
    """P1 回归：判分重排不得影响“下一题”的计算（快照 ids）。"""

    def test_wrong_answer_uses_pre_reorder_snapshot_for_next(self):
        """review 范围 q0 答错后按原顺序应轮到 q1，而不是被重排到末尾。"""
        today = timezone.localdate()
        for question in self.questions[:2]:
            WrongQuestion.objects.create(
                user=self.user,
                question=question,
                last_wrong_at=timezone.now(),
                wrong_count=1,
                review_stage=0,
                next_review_at=today,
                mastered_at=None,
            )
        response = self.client.post(
            reverse("practice-verdict"),
            {"qid": self.questions[0].pk, "scope": "review", "result": "wrong"},
        )

        # 结果页回到刚作答的 q0（q0 答错后已排到明天、掉出复习列表）；
        # 页面上的"下一题"链接按重算列表应指向 q1，不会因列表变化漂移或丢题
        self.assertRedirects(
            response,
            reverse("practice")
            + f"?qid={self.questions[0].pk}&scope=review&outcome=wrong",
            fetch_redirect_response=False,
        )
        page = self.client.get(response.url)
        self.assertContains(page, self.questions[0].stem_md)
        self.assertContains(
            page, f"?qid={self.questions[1].pk}&scope=review"
        )

    def test_verdict_with_non_digit_qid_returns_404(self):
        response = self.client.post(
            reverse("practice-verdict"),
            {"qid": "abc", "scope": "review", "result": "correct"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(AnswerRecord.objects.count(), 0)

    def test_empty_scope_does_not_write_progress(self):
        """范围为空串（全站随机单题）不写任何断点。"""
        self.client.post(
            reverse("practice-verdict"),
            {"qid": self.questions[0].pk, "scope": "", "result": "correct"},
        )

        self.assertFalse(
            PracticeProgress.objects.filter(user=self.user, scope="").exists()
        )
        self.assertFalse(
            PracticeProgress.objects.filter(user=self.user).exists()
        )


class ManualWrongEntryTests(LearningBaseTests):
    def test_wrong_add_seeds_review_schedule(self):
        question = self.questions[0]
        self.client.post(
            reverse("wrong-add", args=[question.pk]),
            {"next": reverse("question-detail", args=[question.pk])},
        )

        wrong = WrongQuestion.objects.get(user=self.user, question=question)
        self.assertEqual(wrong.review_stage, 0)
        self.assertEqual(
            wrong.next_review_at, timezone.localdate() + timedelta(days=1)
        )

    def test_unmark_mastered_restarts_review_schedule(self):
        question = self.questions[0]
        wrong = WrongQuestion.objects.create(
            user=self.user,
            question=question,
            wrong_count=3,
            last_wrong_at=timezone.now(),
            review_stage=4,
            next_review_at=None,
            mastered_at=timezone.now(),
        )
        self.client.post(
            reverse("wrong-toggle-mastered", args=[question.pk]),
            {"next": reverse("wrong-questions")},
        )

        wrong.refresh_from_db()
        self.assertIsNone(wrong.mastered_at)
        self.assertEqual(wrong.review_stage, 0)
        self.assertEqual(
            wrong.next_review_at, timezone.localdate() + timedelta(days=1)
        )