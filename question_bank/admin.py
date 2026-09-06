import base64
import mimetypes
from pathlib import Path

from django.contrib import admin
from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms import ModelForm
from django.forms.models import BaseInlineFormSet
from django.utils.html import format_html

from .templatetags.content import render_markdown
from .models import (
    Favorite,
    KnowledgePoint,
    Paper,
    Question,
    QuestionKnowledgePoint,
    WrongQuestion,
)


class QuestionKnowledgePointForm(ModelForm):
    def clean(self):
        cleaned = super().clean()
        # 跳过模型约束预检：换主场景中旧主行与本行在同一表单集提交，
        # 约束校验发生在保存之前（旧行尚未删除）必然误报。语义仍由
        # formset.clean()（恰好一个主）与数据库约束（保存时先删后插）兜底。
        self._validate_constraints = False
        return cleaned


class QuestionKnowledgeInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors) or self.instance.status != Question.Status.PUBLISHED:
            return

        primary_count = sum(
            1
            for form in self.forms
            if form.cleaned_data
            and not form.cleaned_data.get("DELETE", False)
            and form.cleaned_data.get("is_primary", False)
        )
        if primary_count != 1:
            raise ValidationError(
                "Published questions must have exactly one primary knowledge point."
            )


class QuestionKnowledgeInline(admin.TabularInline):
    model = QuestionKnowledgePoint
    form = QuestionKnowledgePointForm
    formset = QuestionKnowledgeInlineFormSet
    extra = 0


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ("edition", "stage", "original_category_label", "status")
    list_filter = ("edition", "stage", "status")
    search_fields = ("title", "original_category_label")


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = (
        "paper", "question_no", "question_type", "review_state", "status"
    )
    list_filter = (
        "paper__edition",
        "paper__stage",
        "question_type",
        "status",
        "text_checked",
        "formula_checked",
        "solution_checked",
    )
    search_fields = ("stem_md", "answer_md", "solution_md")
    readonly_fields = ("source_preview", "rendered_preview", "search_text")
    inlines = (QuestionKnowledgeInline,)
    actions = ("publish_reviewed",)
    fieldsets = (
        ("归属", {"fields": ("paper", "question_no", "sort_order", "question_type", "score")} ),
        ("内容", {"fields": ("stem_md", "answer_md", "solution_md", "rendered_preview")} ),
        ("原卷", {"fields": ("source_page", "source_crop", "source_preview")} ),
        (
            "复核",
            {
                "fields": (
                    "text_checked",
                    "formula_checked",
                    "solution_checked",
                    "unresolved_ocr_items",
                    "katex_errors",
                    "reviewed_by",
                    "reviewed_at",
                    "status",
                )
            },
        ),
        ("搜索", {"fields": ("search_text",), "classes": ("collapse",)}),
    )

    @admin.display(description="复核状态")
    def review_state(self, obj):
        return "通过" if obj.can_publish() else "未通过"

    @admin.display(description="原卷截图")
    def source_preview(self, obj):
        if not obj.source_crop:
            return "未上传校对截图"
        root = Path(settings.REVIEW_ROOT).resolve()
        path = (root / obj.source_crop).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return "校对截图不存在"
        if path.stat().st_size > 5 * 1024 * 1024:
            return "校对截图超过 5 MB"
        mime = mimetypes.guess_type(path.name)[0]
        if mime not in {"image/png", "image/jpeg", "image/webp"}:
            return "校对截图格式必须是 PNG、JPEG 或 WebP"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return format_html(
            '<img src="data:{};base64,{}" alt="原卷第{}页截图" style="max-width:100%;height:auto">',
            mime,
            encoded,
            obj.source_page,
        )

    @admin.display(description="网页渲染预览")
    def rendered_preview(self, obj):
        return format_html(
            '<section class="question-preview"><h3>题干</h3>{}<h3>答案</h3>{}<h3>解析</h3>{}</section>',
            render_markdown(obj.stem_md),
            render_markdown(obj.answer_md),
            render_markdown(obj.solution_md),
        )

    @admin.action(description="发布已通过全部复核的题目")
    def publish_reviewed(self, request, queryset):
        published = 0
        skipped = 0
        for question in queryset.select_related("paper", "reviewed_by"):
            if question.status == Question.Status.REVIEWED and question.can_publish():
                question.status = Question.Status.PUBLISHED
                question.save(update_fields=["status", "search_text", "updated_at"])
                published += 1
            else:
                skipped += 1
        self.message_user(request, f"已发布 {published} 题，跳过 {skipped} 题。")


@admin.register(KnowledgePoint)
class KnowledgePointAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "parent", "sort_order")
    list_filter = ("subject",)
    search_fields = ("name", "slug")


admin.site.register(Favorite)
admin.site.register(WrongQuestion)
