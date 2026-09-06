import csv
import os
import random
import sys
import threading

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import QuestionFilterForm
from .models import (
    AnswerRecord,
    ExamAnswer,
    ExamAttempt,
    Favorite,
    KnowledgePoint,
    Note,
    Paper,
    PracticeProgress,
    Question,
    QuestionKnowledgePoint,
    WrongQuestion,
)
from .queries import filtered_questions, with_user_flags


def _daily_question():
    """以日期为种子的每日一题：当天全站同一题，次日自动更换。"""
    ids = list(
        Question.objects.filter(
            status=Question.Status.PUBLISHED,
            paper__status=Paper.Status.PUBLISHED,
        ).values_list("pk", flat=True)
    )
    if not ids:
        return None
    seed = timezone.localdate().toordinal()
    return Question.objects.select_related("paper").prefetch_related("knowledge_points").get(pk=random.Random(seed).choice(ids))


def home(request):
    context = {
        "filter_form": QuestionFilterForm(),
        "editions": range(1, 18),
        "daily_question": _daily_question(),
    }
    if request.user.is_authenticated:
        today = timezone.localdate()
        # 与 review 范围同款过滤（含题目/试卷已发布）：入口数字与实际复习题数一致
        context["due_count"] = WrongQuestion.objects.filter(
            user=request.user,
            mastered_at__isnull=True,
            next_review_at__lte=today,
            question__status=Question.Status.PUBLISHED,
            question__paper__status=Paper.Status.PUBLISHED,
        ).count()
        context["pending_wrong"] = WrongQuestion.objects.filter(
            user=request.user, mastered_at__isnull=True
        ).count()
        context["progress"] = (
            PracticeProgress.objects.filter(user=request.user)
            .order_by("-updated_at")
            .first()
        )
    return render(request, "home.html", context)


def about(request):
    return render(request, "question_bank/about.html")


def _listing_response(request, force_questions=False):
    questions, form = filtered_questions(request.GET)
    question_mode = force_questions or bool(
        request.GET.get("q")
        or request.GET.get("question_type")
        or request.GET.getlist("knowledge")
    )
    empty_search = force_questions and not any(
        (
            request.GET.get("q", "").strip(),
            request.GET.get("edition"),
            request.GET.get("stage"),
            request.GET.get("question_type"),
            request.GET.getlist("knowledge"),
        )
    )
    if empty_search:
        questions = questions.none()

    if question_mode:
        page_obj = Paginator(with_user_flags(questions, request.user), 20).get_page(
            request.GET.get("page")
        )
    else:
        papers = Paper.objects.filter(status=Paper.Status.PUBLISHED)
        if form.is_valid():
            if form.cleaned_data["edition"]:
                papers = papers.filter(edition=form.cleaned_data["edition"])
            if form.cleaned_data["stage"]:
                papers = papers.filter(stage=form.cleaned_data["stage"])
        else:
            papers = papers.none()
        page_obj = Paginator(papers, 20).get_page(request.GET.get("page"))

    return render(
        request,
        "question_bank/paper_list.html",
        {
            "filter_form": form,
            "page_obj": page_obj,
            "question_mode": question_mode,
            "search_page": force_questions,
        },
    )


def paper_list(request):
    return _listing_response(request)


def search(request):
    return _listing_response(request, force_questions=True)


def paper_detail(request, pk):
    paper = get_object_or_404(Paper, pk=pk, status=Paper.Status.PUBLISHED)
    questions = Question.objects.filter(
        paper=paper, status=Question.Status.PUBLISHED
    ).select_related("paper").prefetch_related("knowledge_points").order_by(
        "sort_order", "pk"
    )
    return render(
        request,
        "question_bank/paper_detail.html",
        {"paper": paper, "questions": with_user_flags(questions, request.user)},
    )


def paper_download(request, pk):
    paper = get_object_or_404(Paper, pk=pk, status=Paper.Status.PUBLISHED)
    if not paper.pdf_file:
        raise Http404("PDF not found")
    filename = f"第{paper.edition}届-{paper.original_category_label}-{paper.get_stage_display()}.pdf"
    return FileResponse(
        paper.pdf_file.open("rb"),
        as_attachment=True,
        filename=filename,
        content_type="application/pdf",
    )


@login_required
def paper_print(request, pk):
    """整卷打印版：?answers=1 附带答案与解析，否则仅题干供作答留白。"""
    paper = get_object_or_404(Paper, pk=pk, status=Paper.Status.PUBLISHED)
    questions = (
        Question.objects.filter(paper=paper, status=Question.Status.PUBLISHED)
        .select_related("paper")
        .prefetch_related("knowledge_points")
        .order_by("sort_order", "pk")
    )
    return render(
        request,
        "question_bank/paper_print.html",
        {
            "paper": paper,
            "questions": questions,
            "show_answers": request.GET.get("answers") == "1",
        },
    )


def question_detail(request, pk):
    questions = Question.objects.filter(
        status=Question.Status.PUBLISHED,
        paper__status=Paper.Status.PUBLISHED,
    ).select_related("paper").prefetch_related("knowledge_points")
    question = get_object_or_404(with_user_flags(questions, request.user), pk=pk)
    siblings = Question.objects.filter(
        paper=question.paper,
        status=Question.Status.PUBLISHED,
        paper__status=Paper.Status.PUBLISHED,
    ).order_by("sort_order", "pk")
    return render(
        request,
        "question_bank/question_detail.html",
        {
            "question": question,
            "user_note": Note.objects.filter(
                user=request.user if request.user.is_authenticated else None,
                question=question,
            ).first(),
            "previous_question": siblings.filter(sort_order__lt=question.sort_order).last(),
            "next_question": siblings.filter(sort_order__gt=question.sort_order).first(),
        },
    )


def _return_url(request, question):
    candidate = request.POST.get("next", "")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse("question-detail", args=[question.pk])


def _published_question(pk):
    return get_object_or_404(
        Question,
        pk=pk,
        status=Question.Status.PUBLISHED,
        paper__status=Paper.Status.PUBLISHED,
    )


@login_required
@require_POST
def favorite_add(request, pk):
    question = _published_question(pk)
    Favorite.objects.get_or_create(user=request.user, question=question)
    messages.success(request, "已加入收藏。")
    return redirect(_return_url(request, question))


@login_required
@require_POST
def favorite_remove(request, pk):
    question = _published_question(pk)
    Favorite.objects.filter(user=request.user, question=question).delete()
    messages.success(request, "已取消收藏。")
    return redirect(_return_url(request, question))


@login_required
@require_POST
def wrong_add(request, pk):
    question = _published_question(pk)
    # 手工加入同样进入复习队列：次日开始间隔复习，否则 next_review_at 为空，
    # 永远无法被 review 范围捞到
    WrongQuestion.objects.get_or_create(
        user=request.user,
        question=question,
        defaults={
            "last_wrong_at": timezone.now(),
            "review_stage": 0,
            "next_review_at": timezone.localdate() + timedelta(days=1),
        },
    )
    messages.success(request, "已加入错题本。")
    return redirect(_return_url(request, question))


@login_required
@require_POST
def wrong_remove(request, pk):
    question = _published_question(pk)
    WrongQuestion.objects.filter(user=request.user, question=question).delete()
    messages.success(request, "已移出错题本。")
    return redirect(_return_url(request, question))


def _personal_list(request, relation, template_name):
    base = Question.objects.filter(**{f"{relation}__user": request.user})
    questions, form = filtered_questions(request.GET, base_queryset=base)
    questions = with_user_flags(questions, request.user)
    page_obj = Paginator(questions, 20).get_page(request.GET.get("page"))
    return render(
        request,
        template_name,
        {"filter_form": form, "page_obj": page_obj, "clear_url": request.path},
    )


@login_required
def favorites(request):
    return _personal_list(request, "favorited_by", "question_bank/favorites.html")


@login_required
def wrong_questions(request):
    mastered_view = request.GET.get("mastered") == "1"
    base = Question.objects.filter(
        marked_wrong_by__user=request.user,
        marked_wrong_by__mastered_at__isnull=not mastered_view,
        status=Question.Status.PUBLISHED,
        paper__status=Paper.Status.PUBLISHED,
    ).annotate(
        wrong_count=F("marked_wrong_by__wrong_count"),
        last_wrong_at=F("marked_wrong_by__last_wrong_at"),
        mastered_at=F("marked_wrong_by__mastered_at"),
        next_review_at=F("marked_wrong_by__next_review_at"),
        review_stage=F("marked_wrong_by__review_stage"),
    )
    questions, form = filtered_questions(request.GET, base_queryset=base)
    questions = with_user_flags(questions, request.user)
    page_obj = Paginator(questions, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "question_bank/wrong_questions.html",
        {
            "filter_form": form,
            "page_obj": page_obj,
            "clear_url": request.path,
            "mastered": mastered_view,
            "today": timezone.localdate(),
        },
    )


@login_required
@require_POST
def wrong_toggle_mastered(request, pk):
    """标记已掌握 / 解除已掌握（错题本显示开关）。"""
    question = _published_question(pk)
    wrong = WrongQuestion.objects.filter(user=request.user, question=question).first()
    if wrong:
        if wrong.mastered_at:
            wrong.mastered_at = None
            # 解除掌握：复位排期，以“新错题”身份重新进入复习队列，
            # 否则 review_stage 停留在旧档位、next_review_at 仍为空
            wrong.review_stage = 0
            wrong.next_review_at = timezone.localdate() + timedelta(days=1)
            wrong.save(update_fields=["mastered_at", "review_stage", "next_review_at"])
            messages.success(request, "已解除掌握标记，重新加入复习队列。")
        else:
            wrong.mastered_at = timezone.now()
            wrong.save(update_fields=["mastered_at"])
            messages.success(request, "已标记为掌握，不再出现在错题复习中。")
    return redirect(_return_url(request, question))


# ---------- 练习模式（P0-1） ----------

# 间隔复习排期：第 1/3/7/15 天各复习一次，四次全对视为掌握
REVIEW_INTERVALS = (1, 3, 7, 15)


def _advance_review(user, question):
    """复习范围答对：推进档位并按间隔排期；第 4 档自动标记掌握。

    档位用 F 表达式自增：并发重复提交时各推一档，不会都基于旧档位写同一值。
    """
    today = timezone.localdate()
    updated = WrongQuestion.objects.filter(
        user=user, question=question, mastered_at__isnull=True
    ).update(review_stage=F("review_stage") + 1)
    if not updated:
        return
    wrong = WrongQuestion.objects.get(user=user, question=question)
    if wrong.review_stage >= 4:
        WrongQuestion.objects.filter(pk=wrong.pk).update(
            review_stage=4, mastered_at=timezone.now(), next_review_at=None
        )
    else:
        WrongQuestion.objects.filter(pk=wrong.pk).update(
            next_review_at=today + timedelta(days=REVIEW_INTERVALS[wrong.review_stage])
        )


def _weak_scope_ids(user):
    """智能组卷：答错最多 Top3 知识点下的已发布题，历史错题优先，随机抽 ≤15 题。

    抽样种子按"用户+当日"固定：练习页 GET 与判分 POST 各自求值本函数，
    必须得到同一份题集，否则判分时当前题可能不在重抽样本里，
    导致提前完成、进度永远存不上。
    """
    top_kps = (
        QuestionKnowledgePoint.objects.filter(
            question__answer_records__user=user,
            question__answer_records__is_correct=False,
            is_primary=True,
        )
        .values("knowledge_point")
        .annotate(errors=Count("id"))
        .order_by("-errors")[:3]
    )
    kp_ids = [row["knowledge_point"] for row in top_kps]
    if not kp_ids:
        return []
    published = Q(
        status=Question.Status.PUBLISHED, paper__status=Paper.Status.PUBLISHED
    )
    ids = list(
        Question.objects.filter(published, knowledge_points__in=kp_ids)
        .distinct()
        .order_by("id")
        .values_list("pk", flat=True)
    )
    if len(ids) <= 15:
        return ids
    wrong_ids = set(
        WrongQuestion.objects.filter(user=user, question_id__in=ids).values_list(
            "question_id", flat=True
        )
    )
    prioritized = [qid for qid in ids if qid in wrong_ids]
    rest = [qid for qid in ids if qid not in wrong_ids]
    fill = max(0, 15 - len(prioritized))
    seed = f"weak:{user.pk}:{timezone.localdate().toordinal()}"
    return prioritized + random.Random(seed).sample(rest, min(fill, len(rest)))


def _practice_scope_ids(scope, user):
    """练习范围 → (标签, 题目 id 有序列表)。"""
    published = Q(status=Question.Status.PUBLISHED, paper__status=Paper.Status.PUBLISHED)
    if scope.startswith("paper:"):
        paper = get_object_or_404(
            Paper, pk=scope.split(":", 1)[1], status=Paper.Status.PUBLISHED
        )
        ids = list(
            Question.objects.filter(published, paper=paper)
            .order_by("sort_order")
            .values_list("pk", flat=True)
        )
        return paper.title, ids
    if scope.startswith("knowledge:"):
        knowledge = get_object_or_404(KnowledgePoint, slug=scope.split(":", 1)[1])
        ids = list(
            Question.objects.filter(published, knowledge_points__slug=knowledge.slug)
            .distinct()
            .order_by("id")
            .values_list("pk", flat=True)
        )
        return knowledge.name, ids
    if scope == "book":
        ids = list(
            Question.objects.filter(
                published, marked_wrong_by__user=user, marked_wrong_by__mastered_at__isnull=True
            )
            .distinct()
            .order_by(
                "-marked_wrong_by__last_wrong_at",
                "marked_wrong_by__pk",
            )
            .values_list("pk", flat=True)
        )
        return "我的错题", ids
    if scope == "review":
        # 今日待复习：已到期且未掌握的错题
        today = timezone.localdate()
        ids = list(
            Question.objects.filter(
                published,
                marked_wrong_by__user=user,
                marked_wrong_by__mastered_at__isnull=True,
                marked_wrong_by__next_review_at__isnull=False,
                marked_wrong_by__next_review_at__lte=today,
            )
            .distinct()
            .order_by(
                "marked_wrong_by__next_review_at",
                "-marked_wrong_by__wrong_count",
                "marked_wrong_by__pk",
            )
            .values_list("pk", flat=True)
        )
        return "今日待复习", ids
    if scope == "weak":
        return "智能组卷 · 薄弱巩固", _weak_scope_ids(user)
    if scope == "all" or not scope:
        ids = list(
            Question.objects.filter(published).order_by("id").values_list("pk", flat=True)
        )
        return "全部真题", ids
    raise Http404("未知的练习范围")


def _practice_exit_url(scope):
    if scope.startswith("paper:"):
        return reverse("paper-detail", args=[scope.split(":", 1)[1]])
    if scope.startswith("knowledge:"):
        return reverse("search") + f"?knowledge={scope.split(':', 1)[1]}"
    if scope in ("book", "review"):
        return reverse("wrong-questions")
    if scope == "weak":
        return reverse("me")
    return reverse("paper-list")


@login_required
@require_POST
def practice_verdict(request):
    """练习判分：答对写记录；答错进错题本并重置复习排期；复习答对推进档位；同步练习进度。"""
    raw_qid = request.POST.get("qid") or ""
    if not raw_qid.isdigit():
        raise Http404("无效的题目编号")
    question = _published_question(raw_qid)
    scope = request.POST.get("scope", "")
    result = request.POST.get("result", "")

    # 进入本时的范围快照：位置与进度都基于该列表计算。
    # 若在写入后再取 ids，错题重排会让"当前题"位置漂移，
    # 极端情况下答错 → 下一题永远不是写错的那题造成的死循环。
    _, ids = _practice_scope_ids(scope, request.user)

    with transaction.atomic():
        if result == "correct":
            AnswerRecord.objects.create(user=request.user, question=question, is_correct=True)
            if scope == "review":
                _advance_review(request.user, question)
        elif result == "wrong":
            AnswerRecord.objects.create(user=request.user, question=question, is_correct=False)
            next_day = timezone.localdate() + timedelta(days=1)
            wrong, created = WrongQuestion.objects.get_or_create(
                user=request.user,
                question=question,
                defaults={
                    "wrong_count": 1,
                    "last_wrong_at": timezone.now(),
                    "review_stage": 0,
                    "next_review_at": next_day,
                },
            )
            if not created:
                # 再答错：回炉重练——已掌握标记一并清除，重新进入复习队列
                WrongQuestion.objects.filter(pk=wrong.pk).update(
                    wrong_count=F("wrong_count") + 1,
                    last_wrong_at=timezone.now(),
                    review_stage=0,
                    next_review_at=next_day,
                    mastered_at=None,
                )
        elif result != "skip":
            return redirect("practice")

        next_qid = None
        position = None
        if question.pk in ids:
            position = ids.index(question.pk) + 1
            if position < len(ids):
                next_qid = ids[position]

        # 进度断点只对题集稳定（不随作答变化）的范围保存：review/book 的列表
        # 会因答对/答错而动态增删，恢复 position 会跳题；空 scope 为全站散题，
        # 无续练逻辑。范围刷完则清除断点。
        if (
            scope
            and not scope.startswith(("review", "book"))
            and question.pk in ids
        ):
            if next_qid is None:
                PracticeProgress.objects.filter(user=request.user, scope=scope).delete()
            else:
                PracticeProgress.objects.update_or_create(
                    user=request.user, scope=scope, defaults={"position": position}
                )

    # 判分后回到刚作答的题展示结果（横幅 + 展开答案 + 下一题/完成按钮）。
    # 不能带着 outcome 跳下一题：模板会把下一题的答案提前展开且不渲染作答表单
    redirect_url = reverse("practice") + f"?qid={question.pk}"
    if scope:
        redirect_url += f"&scope={scope}"
    redirect_url += f"&outcome={result}"
    return redirect(redirect_url)


def _is_published_question(pk):
    return Question.objects.filter(
        pk=pk,
        status=Question.Status.PUBLISHED,
        paper__status=Paper.Status.PUBLISHED,
    ).exists()


@login_required
def practice(request):
    """练习模式：GET 一题一屏；POST 判分后按 outcome 渲染结果再跳下一题。"""
    scope = request.GET.get("scope", "")
    outcome = request.GET.get("outcome", "")
    done = request.GET.get("done") == "1"
    fresh = request.GET.get("fresh") == "1"
    label, ids = _practice_scope_ids(scope, request.user)

    raw_qid = request.GET.get("qid", "")
    current = None
    forced_next = None  # 结果页：本题刚掉出动态范围时，"下一题"指向重算列表开头
    if raw_qid.isdigit():
        qid_int = int(raw_qid)
        if not scope:
            # 无范围直达某题（每日一题等）：单题模式，不显示全库序号
            if _is_published_question(qid_int):
                current = qid_int
                label = "单题练习"
                ids = [qid_int]
        elif qid_int in ids:
            current = qid_int
        elif outcome and _is_published_question(qid_int):
            # 判分结果页：本题可能刚掉出动态范围（复习答对/答错都排到未来），
            # 保持原范围语境渲染结果，"下一题"指向剩余题目的第一题
            current = qid_int
            forced_next = ids[0] if ids else None
        elif _is_published_question(qid_int):
            # 单题模式（每日一题等）：题目不在范围内也允许
            current = qid_int
            label = "单题练习"
            ids = [qid_int]

    resumed_index = None
    if scope and not scope.startswith(("review", "book")):
        # 断点续练只适用于题集稳定的范围（review/book 的题集随作答变化）；
        # "从头开始"顺手清掉旧断点，避免没作答就离开时仍按旧位置续练
        if fresh:
            PracticeProgress.objects.filter(user=request.user, scope=scope).delete()
        elif current is None and ids:
            progress = PracticeProgress.objects.filter(user=request.user, scope=scope).first()
            if progress is not None and progress.position < len(ids):
                current = ids[progress.position]
                resumed_index = progress.position + 1
    if current is None and ids:
        current = ids[0]

    context = {
        "scope": scope,
        "label": label,
        "total": len(ids),
        "outcome": outcome,
        "done": done,
        "exit_url": _practice_exit_url(scope),
    }

    if current is None:
        # 空范围（如智能组卷暂无错题）
        context["empty"] = True
        return render(request, "question_bank/practice.html", context)

    if current in ids:
        position = ids.index(current)
        context["index"] = position + 1
        context["resumed_index"] = resumed_index
        context["next_qid"] = ids[position + 1] if position + 1 < len(ids) else None
    else:
        # 结果页：已作答题掉出动态列表，不计入进度序号
        context["index"] = None
        context["resumed_index"] = resumed_index
        context["next_qid"] = forced_next

    question = (
        Question.objects.filter(pk=current)
        .select_related("paper")
        .prefetch_related("knowledge_points")
        .first()
    )
    context["question"] = question
    wrong = WrongQuestion.objects.filter(user=request.user, question=question).first()
    context["wrong_count"] = wrong.wrong_count if wrong else 0
    return render(request, "question_bank/practice.html", context)


# ---------- 学习统计（P0-3） ----------

@login_required
def me(request):
    period = 30 if request.GET.get("period") == "30" else 7
    records = AnswerRecord.objects.filter(user=request.user)
    total = records.count()
    correct = records.filter(is_correct=True).count()
    accuracy = round(correct / total * 100) if total else None

    today = timezone.localdate()
    start_date = today - timedelta(days=period - 1)
    period_records = records.filter(created_at__date__gte=start_date)
    period_total = period_records.count()
    period_correct = period_records.filter(is_correct=True).count()
    period_accuracy = round(period_correct / period_total * 100) if period_total else None

    # 柱条：7 天按日；30 天按每 5 天一组共 6 组
    group_days = 5 if period == 30 else 1
    counts_by_day = {
        row["created_at__date"]: row["c"]
        for row in period_records.values("created_at__date").annotate(c=Count("id"))
    }
    bars = []
    if period == 30:
        for i in range(5, -1, -1):  # 最旧组在最左，与 7 天图阅读方向一致
            end = today - timedelta(days=i * 5)
            start = end - timedelta(days=4)
            group = sum(
                counts_by_day.get(start + timedelta(days=offset), 0)
                for offset in range(5)
            )
            bars.append({"day": f"{start.strftime('%m-%d')}~{end.strftime('%m-%d')}", "count": group})
    else:
        days = [(today - timedelta(days=offset)) for offset in range(6, -1, -1)]
        bars = [{"day": d.strftime("%m-%d"), "count": counts_by_day.get(d, 0)} for d in days]

    week_max = max((item["count"] for item in bars), default=0)
    for item in bars:
        item["percent"] = int(item["count"] / week_max * 100) if week_max else 0

    weak_points = (
        QuestionKnowledgePoint.objects.filter(
            question__answer_records__user=request.user,
            question__answer_records__is_correct=False,
            is_primary=True,
        )
        .values("knowledge_point__name")
        .annotate(errors=Count("id"))
        .order_by("-errors")[:6]
    )

    return render(
        request,
        "question_bank/me.html",
        {
            "total": total,
            "accuracy": accuracy,
            "favorite_count": Favorite.objects.filter(user=request.user).count(),
            "wrong_pending": WrongQuestion.objects.filter(
                user=request.user, mastered_at__isnull=True
            ).count(),
            "wrong_any": WrongQuestion.objects.filter(user=request.user).count(),
            "note_count": Note.objects.filter(user=request.user).count(),
            "period": period,
            "period_total": period_total,
            "period_accuracy": period_accuracy,
            "week": bars,
            "week_max": week_max,
            "weak_points": weak_points,
            "recent_exam": ExamAttempt.objects.filter(
                user=request.user, finished_at__isnull=False
            ).select_related("paper").first(),
            "desktop_mode": getattr(sys, "frozen", False),
        },
    )


# ---------- 桌面版（PyInstaller exe）辅助 ----------

@login_required
@require_POST
def desktop_quit(request):
    """桌面版专用：停止本次服务进程。仅 exe 打包环境有效，网页/源码运行一律 404。

    用 POST（表单 + CSRF）而非 GET：带副作用的 GET 会被任意网页顶层导航触发。
    """
    import __main__ as _main

    quit_server = getattr(_main, "_request_quit", None)
    if quit_server is None:
        raise Http404
    quit_server()  # run_bank.py 内部负责清理单实例锁并延迟结束进程
    return HttpResponse(
        "题库服务已停止，可以关闭浏览器窗口了。", content_type="text/plain; charset=utf-8"
    )


@login_required
@require_POST
def desktop_open_data_dir(request):
    """桌面版专用：在资源管理器中打开数据目录（数据库/配图/日志都在这里）。

    数据在 %LOCALAPPDATA%\\MathQuestionBank，普通用户不好找，给个一键直达。
    """
    import __main__ as _main

    open_dir = getattr(_main, "_open_data_dir", None)
    if open_dir is None:
        raise Http404
    open_dir()
    return HttpResponse("已在资源管理器中打开数据文件夹。", content_type="text/plain; charset=utf-8")


# ---------- 个人笔记（P2） ----------

@login_required
@require_POST
def note_save(request, pk):
    question = _published_question(pk)
    body = request.POST.get("body", "").strip()
    if request.POST.get("clear") or not body:
        Note.objects.filter(user=request.user, question=question).delete()
        messages.success(request, "笔记已删除。")
    else:
        Note.objects.update_or_create(
            user=request.user, question=question, defaults={"body": body}
        )
        messages.success(request, "笔记已保存。")
    return redirect(_return_url(request, question))


@login_required
def me_notes(request):
    notes = (
        Note.objects.filter(user=request.user)
        .filter(
            question__status=Question.Status.PUBLISHED,
            question__paper__status=Paper.Status.PUBLISHED,
        )
        .select_related("question", "question__paper")
        .prefetch_related("question__knowledge_points")
    )
    page_obj = Paginator(notes, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "question_bank/me_notes.html",
        {"page_obj": page_obj, "clear_url": request.path},
    )


# ---------- 学习数据导出（P2） ----------


def _csv_cell(value):
    """Excel 公式注入防护：以 =、+、-、@、Tab、CR 开头的单元格前置单引号
    （OWASP CSV Injection 前缀清单）。"""
    text = str(value or "")
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


@login_required
def me_export(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="learning-data.csv"'
    response.write("\ufeff")  # Excel 打开时识别 UTF-8
    writer = csv.writer(response)
    writer.writerow(["类型", "届数", "试卷", "题号", "题型", "知识点", "内容", "时间"])

    def write_question_row(writer, kind, question, extra, when):
        points = "、".join(p.name for p in question.knowledge_points.all())
        writer.writerow(
            [
                _csv_cell(kind),
                _csv_cell(question.paper.edition),
                _csv_cell(question.paper.title),
                _csv_cell(question.question_no),
                _csv_cell(question.get_question_type_display()),
                _csv_cell(points),
                _csv_cell(extra),
                when.strftime("%Y-%m-%d %H:%M") if when else "",
            ]
        )

    base = Question.objects.filter(
        status=Question.Status.PUBLISHED,
        paper__status=Paper.Status.PUBLISHED,
    ).select_related("paper").prefetch_related("knowledge_points")

    for record in (
        AnswerRecord.objects.filter(user=request.user)
        .filter(question__in=base)
        .order_by("-created_at")
    ):
        write_question_row(
            writer,
            "作答" + ("对" if record.is_correct else "错"),
            record.question,
            record.question.stem_md.replace("\n", " ")[:100],
            timezone.localtime(record.created_at),
        )
    for fav in Favorite.objects.filter(
        user=request.user, question__in=base
    ).order_by("-created_at"):
        write_question_row(
            writer,
            "收藏",
            fav.question,
            "",
            timezone.localtime(fav.created_at),
        )
    for wrong in WrongQuestion.objects.filter(
        user=request.user, question__in=base
    ).order_by("-last_wrong_at"):
        write_question_row(
            writer,
            f"错题×{wrong.wrong_count}",
            wrong.question,
            "",
            timezone.localtime(wrong.last_wrong_at),
        )
    for note in Note.objects.filter(user=request.user, question__in=base).order_by(
        "-updated_at"
    ):
        write_question_row(
            writer,
            "笔记",
            note.question,
            note.body.replace("\n", " ")[:200],
            timezone.localtime(note.updated_at),
        )
    return response


# ---------- 模拟考试（第三批） ----------

EXAM_DURATION_MINUTES = 120


def _question_score(question):
    """题目分值：显式 0 分按 0 计；未设分值（null）按 1 分。"""
    return question.score if question.score is not None else 1


def _exam_deadline(attempt):
    return attempt.started_at + timedelta(minutes=EXAM_DURATION_MINUTES)


def _exam_questions(paper):
    return list(
        Question.objects.filter(paper=paper, status=Question.Status.PUBLISHED)
        .select_related("paper")
        .prefetch_related("knowledge_points")
        .order_by("sort_order", "pk")
    )


def _settle_exam(attempt, questions):
    """交卷结算（一次且仅一次）：按最终自评写入作答记录与错题本并算分。

    副作用统一收口在这里，考试过程中反复改判只改 ExamAnswer，
    不会反复写入 AnswerRecord / WrongQuestion 污染统计与错题本。
    调用方需持有 attempt 的行锁（select_for_update）。
    """
    answers = {
        item.question_id: item.result for item in attempt.answers.all()
    }
    for question in questions:
        result = answers.get(question.pk, ExamAnswer.Result.UNANSWERED)
        if result == ExamAnswer.Result.CORRECT:
            AnswerRecord.objects.create(
                user=attempt.user, question=question, is_correct=True
            )
        elif result == ExamAnswer.Result.WRONG:
            AnswerRecord.objects.create(
                user=attempt.user, question=question, is_correct=False
            )
            next_day = timezone.localdate() + timedelta(days=1)
            wrong, created = WrongQuestion.objects.get_or_create(
                user=attempt.user,
                question=question,
                defaults={
                    "wrong_count": 1,
                    "last_wrong_at": timezone.now(),
                    "review_stage": 0,
                    "next_review_at": next_day,
                },
            )
            if not created:
                # 再答错：回炉重练——已掌握标记一并清除，重新进入复习队列
                WrongQuestion.objects.filter(pk=wrong.pk).update(
                    wrong_count=F("wrong_count") + 1,
                    last_wrong_at=timezone.now(),
                    review_stage=0,
                    next_review_at=next_day,
                    mastered_at=None,
                )
    total = sum(_question_score(q) for q in questions)
    self_score = sum(
        _question_score(q)
        for q in questions
        if answers.get(q.pk) == ExamAnswer.Result.CORRECT
    )
    attempt.finished_at = timezone.now()
    attempt.total_score = total
    attempt.self_score = self_score
    attempt.save(update_fields=["finished_at", "total_score", "self_score"])


@login_required
@require_POST
def exam_start(request, paper_pk):
    """创建（或回归未完成）考试并进入考试页。"""
    paper = get_object_or_404(Paper, pk=paper_pk, status=Paper.Status.PUBLISHED)
    if not Question.objects.filter(
        paper=paper, status=Question.Status.PUBLISHED
    ).exists():
        raise Http404("该试卷还没有已发布题目")
    # get_or_create + 未完成考试的部分唯一约束：并发双击也只会有一场
    attempt, _ = ExamAttempt.objects.get_or_create(
        user=request.user, paper=paper, finished_at__isnull=True
    )
    return redirect("exam", exam_pk=attempt.pk)


@login_required
def exam_view(request, exam_pk):
    """考试页：整卷题干一屏呈现，隐藏答案；每题三选一自评。"""
    attempt = get_object_or_404(
        ExamAttempt.objects.select_related("paper"), pk=exam_pk, user=request.user
    )
    if attempt.finished_at is not None:
        return redirect("exam-result", exam_pk=attempt.pk)
    if timezone.now() >= _exam_deadline(attempt):
        # 服务端兜底：超过 120 分钟按当前已保存的自评直接结算。
        # 锁内复查 finished_at：与并发的自动/手动交卷赛跑时只结算一次
        with transaction.atomic():
            locked = ExamAttempt.objects.select_for_update().filter(
                pk=attempt.pk, finished_at__isnull=True
            ).first()
            if locked is not None:
                _settle_exam(locked, _exam_questions(attempt.paper))
        return redirect("exam-result", exam_pk=attempt.pk)

    questions = _exam_questions(attempt.paper)
    answers = {
        item["question_id"]: item["result"]
        for item in attempt.answers.values("question_id", "result")
    }
    for question in questions:
        question.user_result = answers.get(question.pk)
    remaining_seconds = max(
        0, int((_exam_deadline(attempt) - timezone.now()).total_seconds())
    )
    return render(
        request,
        "question_bank/exam.html",
        {
            "attempt": attempt,
            "questions": questions,
            "duration_minutes": EXAM_DURATION_MINUTES,
            "remaining_seconds": remaining_seconds,
        },
    )


@login_required
@require_POST
def exam_answer(request, exam_pk):
    """保存一道题的自评（只写 ExamAnswer，不出业务副作用）。"""
    raw_qid = request.POST.get("qid") or ""
    if not raw_qid.isdigit():
        raise Http404("无效的题目编号")
    with transaction.atomic():
        attempt = ExamAttempt.objects.select_for_update().filter(
            pk=exam_pk, user=request.user
        ).first()
        if attempt is None:
            raise Http404("考试不存在")
        if attempt.finished_at is not None:
            # 已交卷（如到时自动交卷与手动交卷赛跑）：带去成绩单而非报错
            return redirect("exam-result", exam_pk=attempt.pk)
        if timezone.now() >= _exam_deadline(attempt):
            # 考试已超时：拒绝新作答，按当前已保存的自评结算
            _settle_exam(attempt, _exam_questions(attempt.paper))
            return redirect("exam-result", exam_pk=attempt.pk)
        question = get_object_or_404(
            Question, pk=int(raw_qid), paper=attempt.paper,
            status=Question.Status.PUBLISHED,
        )
        result = request.POST.get("result", ExamAnswer.Result.UNANSWERED)
        if result not in ExamAnswer.Result.values:
            return redirect("exam", exam_pk=attempt.pk)
        ExamAnswer.objects.update_or_create(
            attempt=attempt, question=question, defaults={"result": result}
        )
    return redirect(reverse("exam", args=[attempt.pk]) + f"#q{question.pk}")


@login_required
@require_POST
def exam_submit(request, exam_pk):
    """交卷：按题目分值（无分值按 1 分）结算总分与自评分。"""
    with transaction.atomic():
        attempt = ExamAttempt.objects.select_for_update().filter(
            pk=exam_pk, user=request.user
        ).first()
        if attempt is None:
            raise Http404("考试不存在")
        if attempt.finished_at is not None:
            # 重复交卷（双击/自动交卷赛跑）：直接带去成绩单，不重复结算
            return redirect("exam-result", exam_pk=attempt.pk)
        _settle_exam(attempt, _exam_questions(attempt.paper))
    return redirect("exam-result", exam_pk=attempt.pk)


@login_required
def exam_result(request, exam_pk):
    """成绩单：总分、正确率、按题型/知识点得分、每题对错明细。"""
    attempt = get_object_or_404(
        ExamAttempt.objects.select_related("paper"), pk=exam_pk, user=request.user
    )
    if attempt.finished_at is None:
        return redirect("exam", exam_pk=attempt.pk)

    questions = _exam_questions(attempt.paper)
    answers = {
        item.question_id: item.result for item in attempt.answers.all()
    }
    question_ids = [q.pk for q in questions]
    for question in questions:
        question.user_result = answers.get(question.pk)
    primary_kps = {
        item["question_id"]: item["knowledge_point__name"]
        for item in QuestionKnowledgePoint.objects.filter(
            question__in=question_ids, is_primary=True
        ).values("question_id", "knowledge_point__name")
    }
    score_of = {q.pk: _question_score(q) for q in questions}
    total = sum(score_of.values())
    achieved = sum(
        score_of[q.pk]
        for q in questions
        if answers.get(q.pk) == ExamAnswer.Result.CORRECT
    )
    accuracy = round(achieved / total * 100) if total else 0
    correct_count = sum(
        1
        for q in questions
        if answers.get(q.pk) == ExamAnswer.Result.CORRECT
    )

    by_type = []
    for type_code, type_label in Question.Type.choices:
        type_questions = [q for q in questions if q.question_type == type_code]
        if not type_questions:
            continue
        type_total = sum(score_of[q.pk] for q in type_questions)
        type_achieved = sum(
            score_of[q.pk]
            for q in type_questions
            if answers.get(q.pk) == ExamAnswer.Result.CORRECT
        )
        by_type.append(
            {
                "label": type_label,
                "total": type_total,
                "achieved": type_achieved,
                "percent": round(type_achieved / type_total * 100) if type_total else 0,
            }
        )

    kp_map = {}
    for q in questions:
        kp_name = primary_kps.get(q.pk)
        if not kp_name:
            continue
        entry = kp_map.setdefault(
            kp_name, {"total": 0, "achieved": 0, "count": 0}
        )
        entry["total"] += score_of[q.pk]
        entry["count"] += 1
        if answers.get(q.pk) == ExamAnswer.Result.CORRECT:
            entry["achieved"] += score_of[q.pk]
    by_kp = [
        {
            "name": name,
            "total": entry["total"],
            "achieved": entry["achieved"],
            "percent": round(entry["achieved"] / entry["total"] * 100)
            if entry["total"]
            else 0,
        }
        for name, entry in kp_map.items()
    ]

    return render(
        request,
        "question_bank/exam_result.html",
        {
            "attempt": attempt,
            "questions": questions,
            "answers": answers,
            "total": total,
            "achieved": achieved,
            "accuracy": accuracy,
            "correct_count": correct_count,
            "by_type": by_type,
            "by_kp": by_kp,
        },
    )


def not_found(request, exception):
    return render(request, "404.html", status=404)
