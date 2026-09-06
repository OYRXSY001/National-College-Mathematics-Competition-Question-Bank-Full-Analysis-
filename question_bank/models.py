import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


MAX_PDF_BYTES = 50 * 1024 * 1024


def validate_pdf(upload):
    if upload.size > MAX_PDF_BYTES:
        raise ValidationError("PDF 不能超过 50 MB。")
    position = upload.tell()
    header = upload.read(5)
    upload.seek(position)
    if header != b"%PDF-":
        raise ValidationError("上传文件不是有效 PDF。")


def paper_pdf_path(instance, filename):
    return f"papers/edition-{instance.edition:02d}/{instance.stage}.pdf"


def normalize_search_text(*parts):
    text = " ".join(part or "" for part in parts)
    text = re.sub(r"\\[A-Za-z]+|[\\{}$^_]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class Paper(models.Model):
    class Stage(models.TextChoices):
        PRELIMINARY = "preliminary", "初赛"
        PRELIMINARY_B = "preliminary_b", "初赛（B类）"
        FINAL_B = "final_b", "决赛（B类）"
        FINAL = "final", "决赛"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        REVIEWED = "reviewed", "已复核"
        PUBLISHED = "published", "已发布"

    edition = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(17)]
    )
    stage = models.CharField(max_length=20, choices=Stage.choices)
    scope_category = models.CharField(
        max_length=20, default="non_math_a", editable=False
    )
    original_category_label = models.CharField(max_length=50)
    title = models.CharField(max_length=200)
    exam_year = models.PositiveSmallIntegerField(blank=True, null=True)
    pdf_file = models.FileField(
        upload_to=paper_pdf_path, validators=[validate_pdf], blank=True
    )
    source_url = models.URLField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-edition", "-stage"]
        constraints = [
            models.CheckConstraint(
                condition=Q(edition__gte=1, edition__lte=17),
                name="paper_edition_1_to_17",
            ),
            models.CheckConstraint(
                condition=Q(scope_category="non_math_a"),
                name="paper_scope_non_math_a",
            ),
            models.CheckConstraint(
                condition=Q(stage__in=["preliminary", "preliminary_b", "final", "final_b"]),
                name="paper_stage_preliminary_or_final",
            ),
            models.UniqueConstraint(
                fields=["edition", "stage"], name="unique_paper_edition_stage"
            ),
        ]

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class KnowledgePoint(models.Model):
    class Subject(models.TextChoices):
        CALCULUS = "calculus", "高等数学"
        FINAL_LINEAR_ALGEBRA = "final_linear_algebra", "决赛·线性代数"

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    subject = models.CharField(max_length=30, choices=Subject.choices)
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, related_name="children", blank=True, null=True
    )
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["subject", "sort_order", "name"]

    def __str__(self):
        return self.name


class Question(models.Model):
    class Type(models.TextChoices):
        FILL_BLANK = "fill_blank", "填空题"
        CALCULATION = "calculation", "计算题"
        PROOF = "proof", "证明题"
        COMPREHENSIVE = "comprehensive", "综合题"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        REVIEWED = "reviewed", "已复核"
        PUBLISHED = "published", "已发布"

    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name="questions")
    question_no = models.CharField(max_length=20)
    sort_order = models.PositiveSmallIntegerField()
    question_type = models.CharField(max_length=30, choices=Type.choices)
    score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    stem_md = models.TextField()
    answer_md = models.TextField(blank=True)
    solution_md = models.TextField()
    search_text = models.TextField(blank=True, editable=False)
    source_page = models.PositiveSmallIntegerField()
    source_crop = models.CharField(max_length=500, blank=True)
    text_checked = models.BooleanField(default=False)
    formula_checked = models.BooleanField(default=False)
    solution_checked = models.BooleanField(default=False)
    unresolved_ocr_items = models.PositiveSmallIntegerField(default=0)
    katex_errors = models.PositiveSmallIntegerField(default=0)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_questions",
        blank=True,
        null=True,
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    knowledge_points = models.ManyToManyField(
        KnowledgePoint, through="QuestionKnowledgePoint", related_name="questions"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["paper", "sort_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["paper", "question_no"], name="unique_question_number_per_paper"
            )
        ]
        indexes = [
            models.Index(fields=["status", "question_type"]),
            models.Index(fields=["paper", "sort_order"]),
        ]

    def can_publish(self):
        if self.pk is None:
            return False
        has_one_primary = (
            self.questionknowledgepoint_set.filter(is_primary=True).count() == 1
        )
        return all(
            (
                self.status in {self.Status.REVIEWED, self.Status.PUBLISHED},
                self.text_checked,
                self.formula_checked,
                self.solution_checked,
                self.reviewed_by_id is not None,
                self.reviewed_at is not None,
                self.unresolved_ocr_items == 0,
                self.katex_errors == 0,
                bool(self.solution_md.strip()),
                has_one_primary,
            )
        )

    def clean(self):
        if self.status == self.Status.PUBLISHED and not self.can_publish():
            raise ValidationError("题目未通过全部发布检查。")

    def save(self, *args, **kwargs):
        self.search_text = normalize_search_text(
            self.paper.title, self.stem_md, self.answer_md, self.solution_md
        )
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"search_text"}
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.paper.title} 第{self.question_no}题"


class QuestionKnowledgePoint(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    knowledge_point = models.ForeignKey(KnowledgePoint, on_delete=models.PROTECT)
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["question", "knowledge_point"],
                name="unique_question_knowledge_point",
            ),
            models.UniqueConstraint(
                fields=["question"],
                condition=Q(is_primary=True),
                name="one_primary_knowledge_per_question",
            ),
        ]


class Favorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites"
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="favorited_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "question"], name="unique_user_favorite"
            )
        ]


class WrongQuestion(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wrong_questions"
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="marked_wrong_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    wrong_count = models.PositiveSmallIntegerField(default=1)
    last_wrong_at = models.DateTimeField(default=timezone.now)
    mastered_at = models.DateTimeField(null=True, blank=True)
    # 间隔复习排期：stage 0-3 → 答对推进；stage 到 4 自动掌握
    review_stage = models.PositiveSmallIntegerField(default=0)
    next_review_at = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-last_wrong_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "question"], name="unique_user_wrong_question"
            )
        ]


class Note(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notes"
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="notes"
    )
    body = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "question"], name="unique_user_note")
        ]


class AnswerRecord(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="answer_records"
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="answer_records"
    )
    is_correct = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
        ]


class PracticeProgress(models.Model):
    """练习进度断点：用户在某练习范围内做到第几题，下次可续刷。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="practice_progress",
    )
    # 最长 scope 形如 "knowledge:<slug>"（slug 最长 100），SQLite 不强制长度
    # 但 PostgreSQL 会，预留到 150
    scope = models.CharField(max_length=150)
    position = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "scope"], name="unique_user_practice_scope"
            )
        ]


class ExamAttempt(models.Model):
    """模拟考试：整卷限时作答，交卷后自评判分生成成绩单。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exam_attempts"
    )
    paper = models.ForeignKey(
        Paper, on_delete=models.CASCADE, related_name="exam_attempts"
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    self_score = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    total_score = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            # 同一张试卷同时只有一场未完成考试（并发双击 start 也只建一场）
            models.UniqueConstraint(
                fields=["user", "paper"],
                condition=models.Q(finished_at__isnull=True),
                name="unique_active_exam_per_paper",
            )
        ]


class ExamAnswer(models.Model):
    """考试中每道题的自评结果。"""

    class Result(models.TextChoices):
        CORRECT = "correct", "答对"
        WRONG = "wrong", "答错"
        UNANSWERED = "unanswered", "未作答"

    attempt = models.ForeignKey(
        ExamAttempt, on_delete=models.CASCADE, related_name="answers"
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="exam_answers"
    )
    result = models.CharField(
        max_length=12, choices=Result.choices, default=Result.UNANSWERED
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "question"], name="unique_exam_answer"
            )
        ]
