from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from question_bank.models import (
    Favorite,
    KnowledgePoint,
    Paper,
    Question,
    QuestionKnowledgePoint,
    WrongQuestion,
)
from question_bank.templatetags.content import render_markdown


class PublicPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reviewer = get_user_model().objects.create_user("view-reviewer")
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
        cls.question = Question.objects.create(
            paper=cls.paper,
            question_no="1",
            sort_order=1,
            question_type="calculation",
            stem_md=r"计算 \(\lim_{x\to0}x\)。",
            answer_md="0",
            solution_md="极限等于零。",
            source_page=1,
            text_checked=True,
            formula_checked=True,
            solution_checked=True,
            reviewed_by=cls.reviewer,
            reviewed_at=timezone.now(),
            status=Question.Status.REVIEWED,
        )
        QuestionKnowledgePoint.objects.create(
            question=cls.question, knowledge_point=cls.knowledge, is_primary=True
        )
        cls.question.status = Question.Status.PUBLISHED
        cls.question.save()
        cls.draft_paper = Paper.objects.create(
            edition=16,
            stage="final",
            original_category_label="非数学A类",
            title="未发布试卷",
        )

    def setUp(self):
        # 站点门禁启用后，所有页面请求都需要登录态。
        self.client.force_login(self.reviewer)

    def test_home_and_paper_list_are_public(self):
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        response = self.client.get(reverse("paper-list"))
        self.assertContains(response, self.paper.title)
        self.assertNotContains(response, self.draft_paper.title)

    def test_list_page_contains_mobile_filter_and_viewport_support(self):
        response = self.client.get(reverse("paper-list"))

        self.assertContains(response, 'name="viewport"')
        self.assertContains(response, 'class="mobile-filter')
        self.assertContains(response, 'class="desktop-filter')

    def test_base_assets_are_discoverable(self):
        for asset in (
            "css/bootstrap.min.css",
            "katex.min.css",
            "katex.min.js",
            "contrib/auto-render.min.js",
        ):
            with self.subTest(asset=asset):
                self.assertIsNotNone(finders.find(asset))

    def test_search_returns_matching_question(self):
        response = self.client.get(reverse("search"), {"q": "极限等于零"})

        self.assertContains(response, "第1题")
        self.assertContains(response, "极限等于零")

    def test_empty_search_does_not_list_every_question(self):
        response = self.client.get(reverse("search"))

        self.assertNotContains(response, "第1题")

    def test_paper_and_question_details_only_show_published_content(self):
        self.assertEqual(
            self.client.get(reverse("paper-detail", args=[self.paper.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("question-detail", args=[self.question.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("paper-detail", args=[self.draft_paper.pk])).status_code,
            404,
        )

    def test_paper_detail_hides_download_when_pdf_is_missing(self):
        response = self.client.get(reverse("paper-detail", args=[self.paper.pk]))

        self.assertNotContains(response, reverse("paper-download", args=[self.paper.pk]))

    def test_paper_detail_links_to_download_when_pdf_exists(self):
        upload = SimpleUploadedFile(
            "paper.pdf", b"%PDF-1.4\n%%EOF\n", content_type="application/pdf"
        )
        self.paper.pdf_file.save(upload.name, upload, save=True)
        self.addCleanup(self.paper.pdf_file.delete, save=False)

        response = self.client.get(reverse("paper-detail", args=[self.paper.pk]))

        self.assertContains(response, reverse("paper-download", args=[self.paper.pk]))
        self.assertContains(response, "下载 PDF")

    def test_paper_detail_uses_sticky_question_navigation(self):
        response = self.client.get(reverse("paper-detail", args=[self.paper.pk]))

        self.assertContains(response, 'class="question-number-nav')

    def test_markdown_escapes_raw_html_and_keeps_latex(self):
        rendered = str(render_markdown(r"<script>alert(1)</script> \(x^2\)"))

        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn(r"\(x^2\)", rendered)

    def test_markdown_does_not_parse_latex_underscores_as_emphasis(self):
        source = r"设 \(\{a_n\}_{n=0}^\infty\)，且 \(a_{n+p}-a_n\to\lambda\)。"

        rendered = str(render_markdown(source))

        self.assertIn(r"\(\{a_n\}_{n=0}^\infty\)", rendered)
        self.assertIn(r"\(a_{n+p}-a_n\to\lambda\)", rendered)
        self.assertNotIn("<em", rendered)

    def test_markdown_drops_dangerous_link_and_image_uris(self):
        rendered = str(
            render_markdown(
                "[script](javascript:alert(1)) "
                "![data](data:text/html;base64,PHNjcmlwdD4=) "
                "[obfuscated](java&#x09;script:alert(1))"
            )
        )

        self.assertNotIn("href=\"javascript:", rendered.lower())
        self.assertNotIn("href=\"java&#x09;script:", rendered.lower())
        self.assertNotIn("src=\"data:", rendered.lower())

    def test_markdown_drops_newline_obfuscated_link_and_image_uris(self):
        rendered = str(
            render_markdown(
                "[line-feed](java\nscript:alert(1)) "
                "![line-feed](java\nscript:alert(1)) "
                "[carriage-return](java\rscript:alert(1)) "
                "![carriage-return](java\rscript:alert(1))"
            )
        )

        self.assertNotRegex(rendered.lower(), r"""(?:href|src)="[^"]*java[\r\n]script:""")

    def test_markdown_keeps_safe_link_uris(self):
        rendered = str(
            render_markdown(
                "[relative](/papers/) [https](https://example.com/) "
                "[email](mailto:study@example.com) ![image](/image.png)"
            )
        )

        self.assertIn('href="/papers/"', rendered)
        self.assertIn('href="https://example.com/"', rendered)
        self.assertIn('href="mailto:study@example.com"', rendered)
        self.assertIn('src="/image.png"', rendered)

    def test_markdown_preserves_private_use_characters_and_latex(self):
        source = "\ue000 \ue001 \ue002 \ue003 \\(x^2\\)"

        rendered = str(render_markdown(source))

        self.assertIn("\ue000 \ue001 \ue002 \ue003", rendered)
        self.assertIn(r"\(x^2\)", rendered)

    def test_markdown_latex_placeholders_do_not_collide_with_source(self):
        source = "\ue000katex-formula-0\ue001 \\(x^2\\) \\(y^2\\)"

        rendered = str(render_markdown(source))

        self.assertIn("\ue000katex-formula-0\ue001", rendered)
        self.assertIn(r"\(x^2\)", rendered)
        self.assertIn(r"\(y^2\)", rendered)


class UserQuestionListTests(PublicPageTests):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user("collector", password="pass-12345")

    def test_anonymous_user_cannot_add_favorite(self):
        self.client.logout()
        response = self.client.post(reverse("favorite-add", args=[self.question.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_mutation_routes_are_post_only(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("favorite-add", args=[self.question.pk]))

        self.assertEqual(response.status_code, 405)

    def test_add_and_remove_favorite_are_idempotent(self):
        self.client.force_login(self.user)
        add_url = reverse("favorite-add", args=[self.question.pk])
        remove_url = reverse("favorite-remove", args=[self.question.pk])

        self.client.post(add_url)
        self.client.post(add_url)
        self.assertEqual(Favorite.objects.filter(user=self.user, question=self.question).count(), 1)

        self.client.post(remove_url)
        self.client.post(remove_url)
        self.assertFalse(Favorite.objects.filter(user=self.user, question=self.question).exists())

    def test_user_only_sees_own_favorites_and_wrong_questions(self):
        other = get_user_model().objects.create_user("other")
        Favorite.objects.create(user=other, question=self.question)
        WrongQuestion.objects.create(user=other, question=self.question)
        own_favorite = Favorite.objects.create(user=self.user, question=self.question)
        own_wrong_question = WrongQuestion.objects.create(user=self.user, question=self.question)
        self.client.force_login(self.user)

        favorites = self.client.get(reverse("favorites"))
        wrong_questions = self.client.get(reverse("wrong-questions"))

        favorite_questions = list(favorites.context["page_obj"].object_list)
        wrong_question_questions = list(wrong_questions.context["page_obj"].object_list)
        self.assertEqual(favorite_questions, [self.question])
        self.assertEqual(wrong_question_questions, [self.question])
        self.assertTrue(favorite_questions[0].is_favorite)
        self.assertTrue(wrong_question_questions[0].is_wrong)
        self.assertEqual(own_favorite.question, favorite_questions[0])
        self.assertEqual(own_wrong_question.question, wrong_question_questions[0])

    def test_wrong_question_add_and_remove(self):
        self.client.force_login(self.user)

        self.client.post(reverse("wrong-add", args=[self.question.pk]))
        self.assertTrue(WrongQuestion.objects.filter(user=self.user, question=self.question).exists())
        self.client.post(reverse("wrong-remove", args=[self.question.pk]))
        self.assertFalse(WrongQuestion.objects.filter(user=self.user, question=self.question).exists())

    def test_external_next_falls_back_to_question_detail(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("favorite-add", args=[self.question.pk]),
            {"next": "https://evil.example/steal"},
        )

        self.assertRedirects(response, reverse("question-detail", args=[self.question.pk]))

    def test_mutations_reject_unpublished_question(self):
        draft = Question.objects.create(
            paper=self.draft_paper,
            question_no="1",
            sort_order=1,
            question_type="calculation",
            stem_md="draft",
            solution_md="draft",
            source_page=1,
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("favorite-add", args=[draft.pk]))

        self.assertEqual(response.status_code, 404)

    def test_personal_lists_keep_filters_when_paginating(self):
        reviewer = get_user_model().objects.get(username="view-reviewer")
        questions = []
        for number in range(2, 23):
            questions.append(
                Question.objects.create(
                    paper=self.paper,
                    question_no=str(number),
                    sort_order=number,
                    question_type="calculation",
                    stem_md=f"pagination page-marker-{number}",
                    solution_md="solution",
                    source_page=number,
                    text_checked=True,
                    formula_checked=True,
                    solution_checked=True,
                    reviewed_by=reviewer,
                    reviewed_at=timezone.now(),
                    status=Question.Status.REVIEWED,
                )
            )
        for question in questions:
            QuestionKnowledgePoint.objects.create(
                question=question, knowledge_point=self.knowledge, is_primary=True
            )
            question.status = Question.Status.PUBLISHED
            question.save()
        Favorite.objects.bulk_create(Favorite(user=self.user, question=question) for question in questions)
        WrongQuestion.objects.bulk_create(WrongQuestion(user=self.user, question=question) for question in questions)
        self.client.force_login(self.user)

        favorites = self.client.get(reverse("favorites"), {"q": "pagination"})
        wrong_questions = self.client.get(reverse("wrong-questions"), {"q": "pagination"})
        favorite_page_two = self.client.get(reverse("favorites"), {"q": "pagination", "page": 2})

        expected_link = "?q=pagination&amp;page=2"
        self.assertContains(favorites, expected_link)
        self.assertContains(wrong_questions, expected_link)
        self.assertEqual(favorite_page_two.context["page_obj"].number, 2)
        self.assertContains(favorite_page_two, "page-marker-22")

    def test_personal_filter_clear_links_stay_on_current_list(self):
        self.client.force_login(self.user)

        favorites = self.client.get(reverse("favorites"), {"q": "anything"})
        wrong_questions = self.client.get(reverse("wrong-questions"), {"q": "anything"})

        self.assertContains(favorites, f'href="{reverse("favorites")}"')
        self.assertContains(wrong_questions, f'href="{reverse("wrong-questions")}"')
