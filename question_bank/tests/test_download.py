import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from question_bank.models import Paper


class PaperDownloadTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("download-tester")
        self.client.force_login(self.user)
        self.media_root = tempfile.TemporaryDirectory()
        self.settings = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.addCleanup(self.media_root.cleanup)

    def create_paper(self, **kwargs):
        values = {
            "edition": 17,
            "stage": Paper.Stage.PRELIMINARY,
            "original_category_label": "非数学A类",
            "title": "第17届非数学A类初赛",
            "status": Paper.Status.PUBLISHED,
        }
        values.update(kwargs)
        return Paper.objects.create(**values)

    def test_saving_non_pdf_bytes_with_pdf_filename_raises_validation_error(self):
        paper = Paper(
            edition=17,
            stage=Paper.Stage.PRELIMINARY,
            original_category_label="非数学A类",
            title="第17届非数学A类初赛",
            pdf_file=SimpleUploadedFile("paper.pdf", b"not a PDF"),
        )

        with self.assertRaises(ValidationError):
            paper.save()

    def test_download_published_paper_with_pdf_returns_attachment(self):
        paper = self.create_paper()
        paper.pdf_file.save("paper.pdf", SimpleUploadedFile("paper.pdf", b"%PDF-1.4\n"))
        self.addCleanup(paper.pdf_file.delete, save=False)

        response = self.client.get(reverse("paper-download", args=[paper.pk]))
        self.addCleanup(response.close)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response["Content-Disposition"].endswith(".pdf"))

    def test_download_published_paper_without_pdf_returns_404(self):
        paper = self.create_paper()

        response = self.client.get(reverse("paper-download", args=[paper.pk]))

        self.assertEqual(response.status_code, 404)
