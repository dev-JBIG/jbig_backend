import json, secrets, logging, requests
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from vastai_sdk import VastAI
from .models import GpuInstance

logger = logging.getLogger(__name__)
VAST_API_BASE = "https://console.vast.ai/api/v0"
MAX_INSTANCES_PER_USER = 1
DEFAULT_DURATION_MINUTES = 30


def get_vast_client():
    if not settings.VAST_API_KEY:
        raise ValueError("VAST_API_KEY 미설정")
    return VastAI(api_key=settings.VAST_API_KEY)


def check_gpu_permission(user):
    if not user.can_use_gpu:
        return Response({"detail": "GPU 대여 권한 없음"}, status=status.HTTP_403_FORBIDDEN)
    return None


@extend_schema(tags=["GPU"])
class OfferListView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if err := check_gpu_permission(request.user):
            return err

        try:
            client = get_vast_client()
            max_price = request.data.get("max_hourly_price", 1.0)
            query = f"verified=true rentable=true dph_total<={max_price} reliability>0.9"
            result = client.search_offers(query=query, limit=50)

            if isinstance(result, str):
                result = json.loads(result)
            offer_list = result if isinstance(result, list) else result.get("offers", [])

            offers = [{
                "id": o.get("id"),
                "gpu_name": o.get("gpu_name", "Unknown"),
                "vram_gb": round(o.get("gpu_ram", 0) / 1024, 1),
                "hourly_price": o.get("dph_total", 0),
                "reliability": o.get("reliability", 0),
            } for o in offer_list]

            offers.sort(key=lambda x: x["hourly_price"])
            return Response(offers[:10])
        except Exception:
            logger.exception("오퍼 검색 실패")
            return Response({"detail": "오퍼 검색 오류"}, status=status.HTTP_502_BAD_GATEWAY)


@extend_schema(tags=["GPU"])
class InstanceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if err := check_gpu_permission(user):
            return err

        bundle_id = request.data.get("bundle_id")
        if not bundle_id:
            return Response({"detail": "bundle_id 필요"}, status=status.HTTP_400_BAD_REQUEST)

        if GpuInstance.active_count_for_user(user) >= MAX_INSTANCES_PER_USER:
            return Response({"detail": f"최대 {MAX_INSTANCES_PER_USER}개 제한"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            jupyter_token = secrets.token_hex(32)
            resp = requests.put(
                f"{VAST_API_BASE}/asks/{bundle_id}/",
                headers={"Authorization": f"Bearer {settings.VAST_API_KEY}", "Content-Type": "application/json"},
                json={
                    "client_id": "me",
                    "image": request.data.get("image", "pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime"),
                    "disk": request.data.get("disk", 50),
                    "runtype": "jupyter_direct",
                    "use_jupyter_lab": True,
                    "jupyter_dir": "/workspace",
                    "extra_env": {"JUPYTER_TOKEN": jupyter_token},
                },
                timeout=60,
            )

            if not resp.ok:
                logger.error(f"Vast API 오류: {resp.status_code}")
                return Response({"detail": "인스턴스 생성 오류"}, status=status.HTTP_502_BAD_GATEWAY)

            result = resp.json() if resp.text else {}
            instance_id = result.get("new_contract") or result.get("id")
            if not instance_id:
                return Response({"detail": "인스턴스 ID 없음"}, status=status.HTTP_502_BAD_GATEWAY)

            expires_at = timezone.now() + timedelta(minutes=DEFAULT_DURATION_MINUTES)
            GpuInstance.objects.create(
                user=user, vast_instance_id=str(instance_id), offer_id=str(bundle_id),
                gpu_name=request.data.get("gpu_name", ""), hourly_price=request.data.get("hourly_price", 0),
                jupyter_token=jupyter_token, expires_at=expires_at,
            )
            return Response({"id": instance_id, "status": "starting", "jupyter_token": jupyter_token, "expires_at": expires_at.isoformat()})
        except Exception:
            logger.exception("인스턴스 생성 실패")
            return Response({"detail": "인스턴스 생성 오류"}, status=status.HTTP_502_BAD_GATEWAY)


@extend_schema(tags=["GPU"])
class InstanceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_instance(self, user, instance_id):
        try:
            return GpuInstance.objects.get(user=user, vast_instance_id=str(instance_id), status__in=['starting', 'running'])
        except GpuInstance.DoesNotExist:
            return None

    def get(self, request, instance_id):
        gpu_inst = self._get_instance(request.user, instance_id)
        if not gpu_inst:
            return Response({"detail": "인스턴스 없음"}, status=status.HTTP_404_NOT_FOUND)

        try:
            result = get_vast_client().show_instances()
            if isinstance(result, str):
                result = json.loads(result)
            instances = result if isinstance(result, list) else result.get("instances", [])

            for inst in instances:
                if str(inst.get("id")) == str(instance_id):
                    actual_status = inst.get("actual_status", "unknown")
                    if actual_status == "running" and gpu_inst.status != "running":
                        gpu_inst.status = "running"
                        gpu_inst.save(update_fields=['status'])

                    # jupyter url 구성
                    jupyter_url = inst.get("jupyter_url") or ""
                    if not jupyter_url:
                        ip, ports = inst.get("public_ipaddr"), inst.get("ports", {})
                        if ip and ports:
                            port_key = next((k for k in ports if "8080" in k), None)
                            if port_key and ports[port_key]:
                                jupyter_url = f"https://{ip}:{ports[port_key][0].get('HostPort', '8080')}/"

                    # 토큰 추가
                    token = gpu_inst.jupyter_token or inst.get("jupyter_token", "")
                    if jupyter_url and token and "token=" not in jupyter_url:
                        jupyter_url += ("&" if "?" in jupyter_url else "?") + f"token={token}"

                    return Response({
                        "id": inst.get("id"), "status": actual_status, "jupyter_url": jupyter_url,
                        "expires_at": gpu_inst.expires_at.isoformat(),
                    })

            # vast에서 못 찾음 = 종료됨
            gpu_inst.status, gpu_inst.terminated_at = "terminated", timezone.now()
            gpu_inst.save(update_fields=['status', 'terminated_at'])
            return Response({"detail": "인스턴스 없음"}, status=status.HTTP_404_NOT_FOUND)
        except Exception:
            logger.exception("인스턴스 조회 실패")
            return Response({"detail": "조회 오류"}, status=status.HTTP_502_BAD_GATEWAY)

    def patch(self, request, instance_id):
        gpu_inst = self._get_instance(request.user, instance_id)
        if not gpu_inst:
            return Response({"detail": "인스턴스 없음"}, status=status.HTTP_404_NOT_FOUND)

        gpu_inst.expires_at = timezone.now() + timedelta(minutes=DEFAULT_DURATION_MINUTES)
        gpu_inst.save(update_fields=['expires_at'])
        return Response({"expires_at": gpu_inst.expires_at.isoformat()})

    def delete(self, request, instance_id):
        gpu_inst = self._get_instance(request.user, instance_id)
        if not gpu_inst:
            return Response({"detail": "인스턴스 없음"}, status=status.HTTP_404_NOT_FOUND)

        try:
            get_vast_client().destroy_instance(ID=instance_id)
            gpu_inst.status, gpu_inst.terminated_at = "terminated", timezone.now()
            gpu_inst.save(update_fields=['status', 'terminated_at'])
            return Response({"detail": "종료됨"})
        except Exception:
            logger.exception("인스턴스 종료 실패")
            return Response({"detail": "종료 오류"}, status=status.HTTP_502_BAD_GATEWAY)


@extend_schema(tags=["GPU"])
class MyInstancesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        instances = GpuInstance.objects.filter(user=request.user, status__in=['starting', 'running'])
        return Response([{
            "id": i.vast_instance_id, "gpu_name": i.gpu_name, "status": i.status,
            "expires_at": i.expires_at.isoformat(),
        } for i in instances])
