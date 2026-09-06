from django.db.models import Exists, OuterRef, Q

from .forms import QuestionFilterForm
from .models import Favorite, Note, Question, WrongQuestion


def filtered_questions(params, base_queryset=None):
    queryset = base_queryset if base_queryset is not None else Question.objects.all()
    queryset = queryset.filter(
        status=Question.Status.PUBLISHED,
        paper__status="published",
    )
    form = QuestionFilterForm(params)
    if not form.is_valid():
        return queryset.none(), form

    data = form.cleaned_data
    if data["edition"]:
        queryset = queryset.filter(paper__edition=data["edition"])
    if data["stage"]:
        queryset = queryset.filter(paper__stage=data["stage"])
    if data["question_type"]:
        queryset = queryset.filter(question_type=data["question_type"])
    if data["knowledge"]:
        queryset = queryset.filter(knowledge_points__slug__in=data["knowledge"])
    if data["q"]:
        keyword = data["q"].strip()
        queryset = queryset.filter(
            Q(search_text__icontains=keyword)
            | Q(paper__title__icontains=keyword)
            | Q(knowledge_points__name__icontains=keyword)
        )

    return queryset.select_related("paper").prefetch_related("knowledge_points").distinct(), form


def with_user_flags(queryset, user):
    if not user.is_authenticated:
        return queryset.annotate(
            is_favorite=Exists(Favorite.objects.none()),
            is_wrong=Exists(WrongQuestion.objects.none()),
            has_note=Exists(Note.objects.none()),
        )
    return queryset.annotate(
        is_favorite=Exists(
            Favorite.objects.filter(user=user, question_id=OuterRef("pk"))
        ),
        is_wrong=Exists(
            WrongQuestion.objects.filter(user=user, question_id=OuterRef("pk"))
        ),
        has_note=Exists(Note.objects.filter(user=user, question_id=OuterRef("pk"))),
    )
