"""安全回归：markdown 属性注入、中间件路径绕过、CSV 公式注入、兄弟题可见性。"""
import csv
import html.parser

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from question_bank.models import (
    AnswerRecord,
    KnowledgePoint,
    Note,
    Paper,
    Question,
    QuestionKnowledgePoint,
    WrongQuestion,
)
from question_bank.templatetags.content import render_markdown


def _collect_attributes(html_text):
    """解析渲染后的 HTML，返回 {tag: [(attr, value), ...]}。"""
    collector = []

    class Parser(html.parser.HTMLParser):
        def handle_starttag(self, tag, attrs):
            collector.append((tag, attrs))

    parser = Parser()
    parser.feed(html_text)
    parser.close()
    return collector


class MarkdownSanitizationTests(TestCase):
    """render_markdown 输出必须可安全放进 HTML。"""

    def render(self, md):
        return render_markdown(md)

    def test_event_handler_attributes_are_removed(self):
        result = self.render('![x](http://a.test/x.png "t") {.x onerror="alert(1)"}')
        tags = _collect_attributes(result)
        for _, attrs in tags:
            self.assertFalse(
                any(name.startswith("on") for name, _ in attrs),
                f"发现事件属性：{attrs}",
            )

    def test_attr_list_injection_is_not_executed(self):
        result = self.render("正文\n{: .text-danger onclick=\"alert(1)\"}")
        # attr_list 未启用：注入语法原样呈现为文本，而不是成为真实属性
        tags = _collect_attributes(result)
        for _, attrs in tags:
            self.assertFalse(
                any(name in {"onclick", "class"} for name, _ in attrs),
                f"属性被注入为 HTML 属性：{attrs}",
            )
        self.assertIn("alert(1)", result)  # 保留为可见文本，而不是可执行属性

    def test_javascript_href_is_stripped(self):
        result = self.render('[点我](javascript:alert(1))')
        tags = _collect_attributes(result)
        for tag, attrs in tags:
            if tag == "a":
                self.assertFalse(
                    any(name == "href" for name, _ in attrs),
                    "javascript: 链接不应保留 href",
                )

    def test_http_and_mailto_links_are_kept(self):
        result = self.render('[官网](https://example.com) [邮箱](mailto:a@b.cn)')
        self.assertIn('href="https://example.com"', result)
        self.assertIn('href="mailto:a@b.cn"', result)

    def test_katex_formulas_survive(self):
        result = self.render(r"内联公式 $x_1 + y^2$ 与 $$ \int_0^1 x\,dx $$")
        self.assertIn(r"$x_1 + y^2$", result)
        self.assertNotIn("<script>", result)

    def test_script_tag_is_escaped(self):
        result = self.render("<script>alert(1)</script>")
        self.assertNotIn("<script>", result)

    def test_raw_html_event_attribute_never_becomes_attribute(self):
        result = self.render('<img src="x" onerror="alert(1)"> 你好')
        for tag, attrs in _collect_attributes(result):
            if tag == "img":
                self.assertEqual(attrs, [])  # 原始 HTML 被整体转义


class MiddlewareBypassTests(TestCase):
    def test_unauthenticated_paper_page_redirects_to_login(self):
        response = self.client.get(reverse("paper-list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_dotdot_segments_cannot_bypass_gate(self):
        # /static/../papers/ 归一化后不再是静态前缀 → 应被门禁拦下
        response = self.client.get("/static/../papers/")
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_static_assets_are_public(self):
        response = self.client.get("/static/css/project.css")
        self.assertNotEqual(response.status_code, 302)


class CsvFormulaInjectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("csv-user")
        cls.reviewer = get_user_model().objects.create_user("csv-reviewer")
        cls.paper = Paper.objects.create(
            edition=17,
            stage="preliminary",
            original_category_label="非数学A类",
            title="CSV测试卷",
            status="published",
        )
        cls.knowledge = KnowledgePoint.objects.create(
            name="公式注入", slug="csv-formula", subject="calculus"
        )
        cls.question = Question.objects.create(
            paper=cls.paper,
            question_no="-1",
            sort_order=1,
            question_type="calculation",
            stem_md="=HYPERLINK(1,2)",
            answer_md="答案",
            solution_md="解析",
            source_page=1,
            text_checked=True,
            formula_checked=True,
            solution_checked=True,
            reviewed_by=cls.reviewer,
            reviewed_at=timezone.now(),
            status=Question.Status.REVIEWED,
        )
        QuestionKnowledgePoint.objects.create(
            question=cls.question,
            knowledge_point=cls.knowledge,
            is_primary=True,
        )
        cls.question.status = Question.Status.PUBLISHED
        cls.question.save()

    def setUp(self):
        self.client.force_login(self.user)

    def test_export_escapes_formula_prefix_cells(self):
        WrongQuestion.objects.create(
            user=self.user, question=self.question, last_wrong_at=timezone.now()
        )
        AnswerRecord.objects.create(
            user=self.user, question=self.question, is_correct=False
        )
        response = self.client.get(reverse("me-export"))
        self.assertEqual(response.status_code, 200)
        rows = list(
            csv.reader(response.content.decode("utf-8-sig").splitlines())
        )
        # 题号"-1"、题干"=HYPERLINK(...)"这类以 - / = 开头的单元格必须带保护
        # 前缀，防止 Excel 把它当公式执行
        self.assertTrue(any(row[3].startswith("'-") for row in rows))
        self.assertTrue(any(row[6].startswith("'=") for row in rows))


class QuestionVisibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("visibility-user")
        cls.reviewer = get_user_model().objects.create_user("visibility-reviewer")
        cls.paper = Paper.objects.create(
            edition=17,
            stage="preliminary",
            original_category_label="非数学A类",
            title="可见性测试卷",
            status="published",
        )
        cls.published = Question.objects.create(
            paper=cls.paper,
            question_no="1",
            sort_order=1,
            question_type="calculation",
            stem_md="已发布",
            answer_md="答案",
            solution_md="解析",
            source_page=1,
            reviewed_by=cls.reviewer,
            reviewed_at=timezone.now(),
            text_checked=True,
            formula_checked=True,
            solution_checked=True,
            status=Question.Status.REVIEWED,
        )
        QuestionKnowledgePoint.objects.create(
            question=cls.published,
            knowledge_point=KnowledgePoint.objects.create(
                name="可见性", slug="visibility", subject="calculus"
            ),
            is_primary=True,
        )
        cls.published.status = Question.Status.PUBLISHED
        cls.published.save()
        cls.drafted = Question.objects.create(
            paper=cls.paper,
            question_no="2",
            sort_order=2,
            question_type="calculation",
            stem_md="草稿",
            answer_md="答案",
            solution_md="解析",
            source_page=2,
            reviewed_by=cls.reviewer,
            reviewed_at=timezone.now(),
            text_checked=True,
            formula_checked=True,
            solution_checked=True,
            status=Question.Status.DRAFT,
        )

    def test_sibling_links_only_point_to_published(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("question-detail", args=[self.published.pk])
        )
        # 唯一已发布题：下一题（草稿）被过滤，页面不应出现“下一题”链接
        self.assertNotContains(response, "下一题")
        self.assertNotContains(response, "草稿")


class DesktopQuitTests(TestCase):
    """桌面版退出入口仅对 PyInstaller 打包产物（sys.frozen）生效，普通部署一律 404。"""

    def test_quit_redirects_unauthenticated_to_login(self):
        # 全站门禁优先：未登录先去登录页，不会提前暴露退出入口
        response = self.client.get(reverse("desktop-quit"))
        self.assertIn(response.status_code, (302, 404, 405))

    def test_quit_requires_post(self):
        # 带副作用的入口用 POST + CSRF：GET 一律 405，防外站顶层导航触发
        user = get_user_model().objects.create_user("desktop-get-user", password="x")
        self.client.force_login(user)
        response = self.client.get(reverse("desktop-quit"))
        self.assertEqual(response.status_code, 405)

    def test_quit_returns_404_in_web_deployment(self):
        user = get_user_model().objects.create_user("desktop-quit-user", password="x")
        self.client.force_login(user)
        response = self.client.post(reverse("desktop-quit"))
        self.assertEqual(response.status_code, 404)


class DesktopOpenDataDirTests(TestCase):
    """「打开数据文件夹」与退出入口同款约束：POST 专用、仅桌面版生效。"""

    def test_anonymous_is_redirected(self):
        response = self.client.get(reverse("desktop-open-data-dir"))
        self.assertIn(response.status_code, (302, 404, 405))

    def test_requires_post(self):
        user = get_user_model().objects.create_user("desktop-dir-get", password="x")
        self.client.force_login(user)
        response = self.client.get(reverse("desktop-open-data-dir"))
        self.assertEqual(response.status_code, 405)

    def test_returns_404_in_web_deployment(self):
        user = get_user_model().objects.create_user("desktop-dir-user", password="x")
        self.client.force_login(user)
        response = self.client.post(reverse("desktop-open-data-dir"))
        self.assertEqual(response.status_code, 404)