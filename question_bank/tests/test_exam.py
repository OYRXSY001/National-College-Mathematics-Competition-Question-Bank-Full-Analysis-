"""第三批新功能测试：模拟考试（自评/交卷/成绩单）。

自评只改 ExamAnswer；作答记录、错题本等业务副作用一律在交卷当刻
一次性结算（_settle_exam），考试中反复改判不再污染统计与错题本。
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from question_bank.models import (
    AnswerRecord,
    ExamAnswer,
    ExamAttempt,
    KnowledgePoint,
    Paper,
    Question,
    QuestionKnowledgePoint,
    WrongQuestion,
)

EXAM_DURATION = timedelta(minutes=120)


class ExamBaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("exam-learner")
        cls.reviewer = get_user_model().objects.create_user("exam-reviewer")
        cls.paper = Paper.objects.create(
            edition=16,
            stage="preliminary",
            original_category_label="非数学A类",
            title="第16届非数学A类初赛",
            status="published",
        )
        cls.draft_paper = Paper.objects.create(
            edition=15,
            stage="final",
            original_category_label="非数学A类",
            title="草稿卷",
        )
        cls.knowledge = KnowledgePoint.objects.create(
            name="级数", slug="series", subject="calculus"
        )
        cls.questions = []
        for number in (1, 2, 3):
            question = Question.objects.create(
                paper=cls.paper,
                question_no=str(number),
                sort_order=number,
                question_type="calculation",
                stem_md=f"考试题 {number}。",
                answer_md=f"答案{number}",
                solution_md=f"解析{number}",
                source_page=number,
                score=5,
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

    def expire_attempt(self, attempt):
        # 把开始时间拨回 121 分钟前，模拟考试超时
        ExamAttempt.objects.filter(pk=attempt.pk).update(
            started_at=timezone.now() - EXAM_DURATION - timedelta(minutes=1)
        )
        attempt.refresh_from_db()


class ExamStartTests(ExamBaseTests):
    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("exam-start", args=[self.paper.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_start_creates_attempt_and_redirects(self):
        response = self.client.post(reverse("exam-start", args=[self.paper.pk]))

        self.assertEqual(response.status_code, 302)
        attempt = ExamAttempt.objects.get(user=self.user, paper=self.paper)
        self.assertEqual(response.url, reverse("exam", args=[attempt.pk]))

    def test_second_start_reuses_in_progress_attempt(self):
        response = self.client.post(reverse("exam-start", args=[self.paper.pk]))
        attempt = ExamAttempt.objects.get(user=self.user, paper=self.paper)

        second = self.client.post(reverse("exam-start", args=[self.paper.pk]))

        self.assertEqual(response.url, reverse("exam", args=[attempt.pk]))
        self.assertEqual(second.url, reverse("exam", args=[attempt.pk]))
        self.assertEqual(
            ExamAttempt.objects.filter(user=self.user, paper=self.paper).count(), 1
        )

    def test_draft_paper_returns_404(self):
        response = self.client.post(reverse("exam-start", args=[self.draft_paper.pk]))
        self.assertEqual(response.status_code, 404)


class ExamFlowTests(ExamBaseTests):
    def setUp(self):
        super().setUp()
        self.attempt = ExamAttempt.objects.create(user=self.user, paper=self.paper)

    def answer(self, question, result):
        return self.client.post(
            reverse("exam-answer", args=[self.attempt.pk]),
            {"qid": question.pk, "result": result},
        )

    def submit(self):
        return self.client.post(reverse("exam-submit", args=[self.attempt.pk]))

    def test_exam_page_hides_answers(self):
        response = self.client.get(reverse("exam", args=[self.attempt.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "考试题 1。")
        self.assertNotContains(response, "答案1")
        self.assertNotContains(response, "解析1")
        self.assertContains(response, "exam-countdown")

    def test_exam_page_renders_remaining_seconds(self):
        response = self.client.get(reverse("exam", args=[self.attempt.pk]))

        self.assertContains(response, 'data-seconds="')
        self.assertContains(response, "exam-countdown")

    def test_answer_saves_self_result_without_business_side_effects(self):
        question = self.questions[0]
        self.answer(question, "correct")

        exam_answer = ExamAnswer.objects.get(
            attempt=self.attempt, question=question
        )
        self.assertEqual(exam_answer.result, "correct")
        # 交卷前不产生作答记录 / 错题本
        self.assertFalse(
            AnswerRecord.objects.filter(
                user=self.user, question=question, is_correct=True
            ).exists()
        )
        self.assertFalse(
            WrongQuestion.objects.filter(user=self.user, question=question).exists()
        )

    def test_wrong_self_result_writes_records_only_after_submit(self):
        question = self.questions[0]
        self.answer(question, "wrong")
        self.assertEqual(
            AnswerRecord.objects.filter(user=self.user, question=question).count(), 0
        )
        self.assertFalse(
            WrongQuestion.objects.filter(user=self.user, question=question).exists()
        )

        self.submit()
        # 交卷后：错题记录 + 错题本，次日进入复习队列
        self.assertTrue(
            AnswerRecord.objects.filter(
                user=self.user, question=question, is_correct=False
            ).exists()
        )
        wrong = WrongQuestion.objects.get(user=self.user, question=question)
        self.assertEqual(wrong.review_stage, 0)
        self.assertEqual(
            wrong.next_review_at, timezone.localdate() + timedelta(days=1)
        )

    def test_unanswered_does_not_write_record(self):
        question = self.questions[0]
        self.answer(question, "unanswered")
        self.submit()
        self.assertEqual(
            AnswerRecord.objects.filter(user=self.user, question=question).count(),
            0,
        )

    def test_reanswer_wrong_then_correct_only_saves_correct_record(self):
        """中间改判过：结算只看最终自评，错题本不再被中间状态污染。"""
        question = self.questions[0]
        self.answer(question, "wrong")
        self.answer(question, "correct")
        self.submit()

        self.assertEqual(
            AnswerRecord.objects.filter(user=self.user, question=question).count(),
            1,
        )
        record = AnswerRecord.objects.get(user=self.user, question=question)
        self.assertTrue(record.is_correct)
        self.assertFalse(
            WrongQuestion.objects.filter(user=self.user, question=question).exists()
        )

    def test_wrong_final_self_result_writes_single_record(self):
        question = self.questions[0]
        self.answer(question, "correct")
        self.answer(question, "wrong")
        self.submit()

        self.assertEqual(
            AnswerRecord.objects.filter(user=self.user, question=question).count(),
            1,
        )
        self.assertFalse(
            AnswerRecord.objects.filter(
                user=self.user, question=question, is_correct=True
            ).exists()
        )
        self.assertTrue(
            WrongQuestion.objects.filter(user=self.user, question=question).exists()
        )

    def test_answer_with_non_digit_qid_returns_404(self):
        response = self.client.post(
            reverse("exam-answer", args=[self.attempt.pk]),
            {"qid": "abc", "result": "correct"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(ExamAnswer.objects.count(), 0)

    def test_expired_answer_forces_settlement(self):
        question = self.questions[0]
        self.answer(question, "correct")
        self.expire_attempt(self.attempt)

        response = self.answer(question, "correct")  # 超时后不再接受新自评

        self.assertRedirects(
            response, reverse("exam-result", args=[self.attempt.pk]),
            fetch_redirect_response=False,
        )
        self.attempt.refresh_from_db()
        self.assertIsNotNone(self.attempt.finished_at)
        # 结算的是超时前的最后一次保存：“答对”（第 1 题 5 分，全卷 15 分）
        self.assertEqual(str(self.attempt.self_score), "5.00")
        self.assertEqual(str(self.attempt.total_score), "15.00")
        self.assertTrue(
            AnswerRecord.objects.filter(
                user=self.user, question=question, is_correct=True
            ).exists()
        )

    def test_expired_view_redirects_to_result_and_settles(self):
        question = self.questions[0]
        self.answer(question, "wrong")
        self.expire_attempt(self.attempt)

        response = self.client.get(reverse("exam", args=[self.attempt.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn("result", response.url)
        self.attempt.refresh_from_db()
        self.assertIsNotNone(self.attempt.finished_at)
        self.assertTrue(
            WrongQuestion.objects.filter(user=self.user, question=question).exists()
        )

    def test_submit_computes_score_with_question_weights(self):
        q1, q2, _ = self.questions
        self.answer(q1, "correct")
        self.answer(q2, "wrong")
        response = self.submit()

        self.assertRedirects(
            response,
            reverse("exam-result", args=[self.attempt.pk]),
            fetch_redirect_response=False,
        )
        self.attempt.refresh_from_db()
        self.assertEqual(str(self.attempt.self_score), "5.00")
        self.assertEqual(str(self.attempt.total_score), "15.00")
        self.assertIsNotNone(self.attempt.finished_at)

    def test_score_falls_back_to_1_when_no_weight(self):
        Question.objects.filter(paper=self.paper).update(score=None)
        for question in self.questions[:2]:
            self.answer(question, "correct")
        self.submit()

        self.attempt.refresh_from_db()
        self.assertEqual(str(self.attempt.self_score), "2.00")
        self.assertEqual(str(self.attempt.total_score), "3.00")

    def test_zero_score_question_counts_as_zero(self):
        q1 = self.questions[0]
        Question.objects.filter(pk=q1.pk).update(score=0)
        self.answer(q1, "correct")
        self.submit()

        self.attempt.refresh_from_db()
        self.assertEqual(str(self.attempt.self_score), "0.00")

    def test_result_page_shows_scores_and_question_states(self):
        q1 = self.questions[0]
        self.answer(q1, "correct")
        self.submit()

        response = self.client.get(reverse("exam-result", args=[self.attempt.pk]))

        self.assertContains(response, "成绩单")
        self.assertContains(response, "5.00")
        self.assertContains(response, "33")
        self.assertContains(response, "答对")
        self.assertContains(response, "级数")
        self.assertContains(response, "解析1")

    def test_finished_attempt_redirects_to_result(self):
        self.submit()
        response = self.client.get(reverse("exam", args=[self.attempt.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("result", response.url)

    def test_submit_after_finish_redirects_to_result(self):
        """重复交卷（双击/自动交卷赛跑）不再报错，直接带去成绩单且不二次结算。"""
        q1 = self.questions[0]
        self.answer(q1, "correct")
        self.submit()
        records_before = AnswerRecord.objects.count()

        response = self.submit()

        self.assertRedirects(
            response,
            reverse("exam-result", args=[self.attempt.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(AnswerRecord.objects.count(), records_before)

    def test_answer_after_finish_redirects_to_result(self):
        self.submit()
        response = self.answer(self.questions[0], "correct")
        self.assertRedirects(
            response,
            reverse("exam-result", args=[self.attempt.pk]),
            fetch_redirect_response=False,
        )

    def test_other_users_cannot_view_attempt(self):
        other = get_user_model().objects.create_user("other")
        self.client.force_login(other)
        response = self.client.get(reverse("exam", args=[self.attempt.pk]))
        self.assertEqual(response.status_code, 404)

    def test_mastered_question_wrong_again_in_exam_reenters_queue(self):
        """交卷结算时已掌握的题再答错：清除掌握标记、重新进入复习队列。"""
        question = self.questions[0]
        WrongQuestion.objects.create(
            user=self.user,
            question=question,
            mastered_at=timezone.now(),
            review_stage=4,
        )
        self.answer(question, "wrong")
        self.submit()

        wrong = WrongQuestion.objects.get(user=self.user, question=question)
        self.assertIsNone(wrong.mastered_at)
        self.assertEqual(wrong.review_stage, 0)


class ExamStartGuardTests(ExamBaseTests):
    def test_start_rejects_get(self):
        """带副作用的开始考试只接受 POST（防浏览器预取/外站导航误触）。"""
        response = self.client.get(reverse("exam-start", args=[self.paper.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(ExamAttempt.objects.count(), 0)

    def test_concurrent_start_cannot_create_two_active_attempts(self):
        """部分唯一约束兜底：同卷未完成考试在数据库层唯一。"""
        from django.db import IntegrityError, transaction

        ExamAttempt.objects.create(user=self.user, paper=self.paper)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExamAttempt.objects.create(user=self.user, paper=self.paper)