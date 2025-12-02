import json
import secrets
import logging
import requests
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
MAX_INSTANCES_PER_USER = 1  # 사용자당 최대 동시 인스턴스 수
DEFAULT_DURATION_MINUTES = 30  # 기본 대여 시간


def get_vast_client():
    api_key = settings.VAST_API_KEY
    if not api_key:
        raise ValueError("VAST_API_KEY가 설정되지 않았습니다.")
    return VastAI(api_key=api_key)


@extend_schema(tags=["GPU"])
class OfferListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="GPU 오퍼 검색",
        description="조건에 맞는 Vast.ai GPU 오퍼를 검색합니다.",
    )
    def post(self, request):
        max_hourly_price = request.data.get("max_hourly_price", 1.0)

        try:
            client = get_vast_client()

            query_parts = [
                "verified=true",
                "rentable=true",
                f"dph_total<={max_hourly_price}",
                "reliability>0.9",
            ]

            query = " ".join(query_parts)
            result = client.search_offers(query=query, limit=50)

            offers = []
            if isinstance(result, str):
                result = json.loads(result)

            offer_list = result if isinstance(result, list) else result.get("offers", [])

            for o in offer_list:
                offers.append({
                    "id": o.get("id"),
                    "gpu_name": o.get("gpu_name", "Unknown"),
                    "vram_gb": round(o.get("gpu_ram", 0) / 1024, 1),
                    "hourly_price": o.get("dph_total", 0),
                    "reliability": o.get("reliability", 0),
                    "hostname": o.get("hostname", ""),
                })

            offers.sort(key=lambda x: x["hourly_price"])
            return Response(offers[:10])

        except Exception as e:
            logger.exception("GPU 오퍼 검색 실패")
            return Response(
                {"detail": "GPU 오퍼 검색 중 오류가 발생했습니다."},
                status=status.HTTP_502_BAD_GATEWAY,
            )


@extend_schema(tags=["GPU"])
class InstanceView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="GPU 인스턴스 생성",
        description="선택한 오퍼로 Vast.ai 인스턴스를 생성합니다.",
    )
    def post(self, request):
        user = request.user
        bundle_id = request.data.get("bundle_id")
        image = request.data.get("image", "pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime")
        disk_gb = request.data.get("disk", 50)
        gpu_name = request.data.get("gpu_name", "")
        hourly_price = request.data.get("hourly_price", 0)

        if not bundle_id:
            return Response(
                {"detail": "bundle_id가 필요합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 사용자당 인스턴스 수 제한 확인
        active_count = GpuInstance.active_count_for_user(user)
        if active_count >= MAX_INSTANCES_PER_USER:
            return Response(
                {"detail": f"동시에 {MAX_INSTANCES_PER_USER}개 이상의 인스턴스를 생성할 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.VAST_API_KEY}",
            }

            jupyter_token = secrets.token_hex(32)

            payload = {
                "client_id": "me",
                "image": image,
                "disk": disk_gb,
                "runtype": "jupyter_direct",
                "use_jupyter_lab": True,
                "jupyter_dir": "/workspace",
                "extra_env": {
                    "JUPYTER_TOKEN": jupyter_token,
                },
            }

            resp = requests.put(
                f"{VAST_API_BASE}/asks/{bundle_id}/",
                headers=headers,
                json=payload,
                timeout=60,
            )

            if not resp.ok:
                logger.error(f"Vast.ai API 오류: {resp.status_code} - {resp.text}")
                return Response(
                    {"detail": "인스턴스 생성 중 오류가 발생했습니다."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            result = resp.json() if resp.text else {}
            instance_id = result.get("new_contract") or result.get("id") or result.get("instance_id")

            if not instance_id:
                logger.error(f"인스턴스 ID 없음: {result}")
                return Response(
                    {"detail": "인스턴스 생성 응답이 올바르지 않습니다."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            # DB에 인스턴스 기록
            expires_at = timezone.now() + timedelta(minutes=DEFAULT_DURATION_MINUTES)
            gpu_instance = GpuInstance.objects.create(
                user=user,
                vast_instance_id=str(instance_id),
                offer_id=str(bundle_id),
                gpu_name=gpu_name,
                hourly_price=hourly_price,
                status='starting',
                jupyter_token=jupyter_token,
                expires_at=expires_at,
            )

            return Response({
                "id": instance_id,
                "status": "starting",
                "jupyter_token": jupyter_token,
                "expires_at": expires_at.isoformat(),
            })

        except Exception as e:
            logger.exception("인스턴스 생성 실패")
            return Response(
                {"detail": "인스턴스 생성 중 오류가 발생했습니다."},
                status=status.HTTP_502_BAD_GATEWAY,
            )


@extend_schema(tags=["GPU"])
class InstanceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_user_instance(self, user, instance_id):
        """사용자 소유의 인스턴스만 반환"""
        try:
            return GpuInstance.objects.get(
                user=user,
                vast_instance_id=str(instance_id),
                status__in=['starting', 'running']
            )
        except GpuInstance.DoesNotExist:
            return None

    @extend_schema(
        summary="GPU 인스턴스 조회",
        description="인스턴스 상태와 IP 정보를 조회합니다.",
    )
    def get(self, request, instance_id):
        user = request.user

        # 소유권 확인
        gpu_instance = self.get_user_instance(user, instance_id)
        if not gpu_instance:
            return Response(
                {"detail": "인스턴스를 찾을 수 없거나 접근 권한이 없습니다."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            client = get_vast_client()
            result = client.show_instances()

            if isinstance(result, str):
                result = json.loads(result)

            instances = result if isinstance(result, list) else result.get("instances", [])

            for inst in instances:
                if str(inst.get("id")) == str(instance_id):
                    public_ip = inst.get("public_ipaddr")
                    ports = inst.get("ports", {})
                    actual_status = inst.get("actual_status", "unknown")
                    vast_jupyter_token = inst.get("jupyter_token", "")

                    # DB 상태 업데이트
                    if actual_status == "running" and gpu_instance.status != "running":
                        gpu_instance.status = "running"
                        gpu_instance.save(update_fields=['status'])

                    jupyter_url = inst.get("jupyter_url")
                    if not jupyter_url and public_ip and ports:
                        port_key = next((k for k in ports.keys() if "8080" in k), None)
                        if port_key and ports[port_key]:
                            host_port = ports[port_key][0].get("HostPort", "8080")
                            jupyter_url = f"https://{public_ip}:{host_port}/"

                    # DB에 저장된 토큰 또는 Vast.ai 토큰 사용
                    token_to_use = gpu_instance.jupyter_token or vast_jupyter_token
                    if jupyter_url and token_to_use and "token=" not in jupyter_url:
                        separator = "&" if "?" in jupyter_url else "?"
                        jupyter_url = f"{jupyter_url}{separator}token={token_to_use}"

                    return Response({
                        "id": inst.get("id"),
                        "status": actual_status,
                        "public_ip": public_ip,
                        "ports": ports,
                        "jupyter_url": jupyter_url,
                        "expires_at": gpu_instance.expires_at.isoformat(),
                    })

            # Vast.ai에서 인스턴스를 찾을 수 없음 (삭제됨)
            gpu_instance.status = "terminated"
            gpu_instance.terminated_at = timezone.now()
            gpu_instance.save(update_fields=['status', 'terminated_at'])

            return Response(
                {"detail": "인스턴스를 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            logger.exception("인스턴스 조회 실패")
            return Response(
                {"detail": "인스턴스 조회 중 오류가 발생했습니다."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    @extend_schema(
        summary="GPU 인스턴스 연장",
        description="인스턴스 만료 시간을 연장합니다.",
    )
    def patch(self, request, instance_id):
        user = request.user

        gpu_instance = self.get_user_instance(user, instance_id)
        if not gpu_instance:
            return Response(
                {"detail": "인스턴스를 찾을 수 없거나 접근 권한이 없습니다."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 30분 연장
        gpu_instance.expires_at = timezone.now() + timedelta(minutes=DEFAULT_DURATION_MINUTES)
        gpu_instance.save(update_fields=['expires_at'])

        return Response({
            "detail": "인스턴스가 연장되었습니다.",
            "expires_at": gpu_instance.expires_at.isoformat(),
        })

    @extend_schema(
        summary="GPU 인스턴스 종료",
        description="인스턴스를 완전히 삭제합니다.",
    )
    def delete(self, request, instance_id):
        user = request.user

        gpu_instance = self.get_user_instance(user, instance_id)
        if not gpu_instance:
            return Response(
                {"detail": "인스턴스를 찾을 수 없거나 접근 권한이 없습니다."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            client = get_vast_client()
            client.destroy_instance(ID=instance_id)

            # DB 상태 업데이트
            gpu_instance.status = "terminated"
            gpu_instance.terminated_at = timezone.now()
            gpu_instance.save(update_fields=['status', 'terminated_at'])

            return Response({"detail": "인스턴스가 종료되었습니다."})

        except Exception as e:
            logger.exception("인스턴스 종료 실패")
            return Response(
                {"detail": "인스턴스 종료 중 오류가 발생했습니다."},
                status=status.HTTP_502_BAD_GATEWAY,
            )


@extend_schema(tags=["GPU"])
class MyInstancesView(APIView):
    """사용자의 인스턴스 목록 조회"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="내 GPU 인스턴스 목록",
        description="현재 사용자의 활성 GPU 인스턴스 목록을 조회합니다.",
    )
    def get(self, request):
        instances = GpuInstance.objects.filter(
            user=request.user,
            status__in=['starting', 'running']
        )
        return Response([{
            "id": inst.vast_instance_id,
            "gpu_name": inst.gpu_name,
            "hourly_price": float(inst.hourly_price),
            "status": inst.status,
            "created_at": inst.created_at.isoformat(),
            "expires_at": inst.expires_at.isoformat(),
        } for inst in instances])
