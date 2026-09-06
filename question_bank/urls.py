from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("papers/", views.paper_list, name="paper-list"),
    path("papers/<int:pk>/", views.paper_detail, name="paper-detail"),
    path("papers/<int:pk>/download/", views.paper_download, name="paper-download"),
    path("questions/<int:pk>/", views.question_detail, name="question-detail"),
    path("questions/<int:pk>/favorite/add/", views.favorite_add, name="favorite-add"),
    path("questions/<int:pk>/favorite/remove/", views.favorite_remove, name="favorite-remove"),
    path("questions/<int:pk>/wrong/add/", views.wrong_add, name="wrong-add"),
    path("questions/<int:pk>/wrong/remove/", views.wrong_remove, name="wrong-remove"),
    path("questions/<int:pk>/wrong/mastered/", views.wrong_toggle_mastered, name="wrong-toggle-mastered"),
    path("questions/<int:pk>/note/", views.note_save, name="note-save"),
    path("papers/<int:pk>/print/", views.paper_print, name="paper-print"),
    path("me/", views.me, name="me"),
    path("me/favorites/", views.favorites, name="favorites"),
    path("me/wrong-questions/", views.wrong_questions, name="wrong-questions"),
    path("me/notes/", views.me_notes, name="me-notes"),
    path("me/export/", views.me_export, name="me-export"),
    path("practice/", views.practice, name="practice"),
    path("practice/verdict/", views.practice_verdict, name="practice-verdict"),
    path("exam/<int:paper_pk>/start/", views.exam_start, name="exam-start"),
    path("exam/<int:exam_pk>/", views.exam_view, name="exam"),
    path("exam/<int:exam_pk>/answer/", views.exam_answer, name="exam-answer"),
    path("exam/<int:exam_pk>/submit/", views.exam_submit, name="exam-submit"),
    path("exam/<int:exam_pk>/result/", views.exam_result, name="exam-result"),
    path("search/", views.search, name="search"),
    path("desktop/quit/", views.desktop_quit, name="desktop-quit"),
    path("desktop/open-data-dir/", views.desktop_open_data_dir, name="desktop-open-data-dir"),
]
