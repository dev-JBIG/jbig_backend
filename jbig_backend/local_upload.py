"""로컬 개발 환경에서 presigned URL 대신 파일을 직접 받는 뷰."""
from django.http import HttpResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .storage import save_local_file


@method_decorator(csrf_exempt, name='dispatch')
class LocalFileUploadView(View):
    """
    PUT 요청으로 파일 바이너리를 받아 media/ 에 저장한다.
    NCP presigned URL처럼 인증 없이 동작 (로컬 전용).
    """

    def put(self, request, file_key):
        if not file_key.startswith('uploads/'):
            return HttpResponse("Invalid file path.", status=400)

        body = request.body
        if not body:
            return HttpResponse("Empty body.", status=400)

        save_local_file(file_key, body)
        return HttpResponse(status=200)
