import json
import requests
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from vastai_sdk import VastAI

VAST_API_BASE = "https://console.vast.ai/api/v0"


def get_vast_client():
    api_key = settings.VAST_API_KEY
    if not api_key:
        raise ValueError("VAST_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
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

            # search_offers 쿼리 구성 (가격 제한 + Jupyter 태그)
            query_parts = [
                "verified=true",
                "rentable=true",
                f"dph_total<={max_hourly_price}",
                "reliability>0.9",
                "jupyter=true",
            ]

            query = " ".join(query_parts)
            result = client.search_offers(query=query, limit=50)

            # 결과 파싱
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

            # 가격순 정렬 후 최대 10개
            offers.sort(key=lambda x: x["hourly_price"])
            return Response(offers[:10])

        except Exception as e:
            return Response(
                {"detail": f"Vast.ai API 오류: {str(e)}"},
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
        bundle_id = request.data.get("bundle_id")
        image = request.data.get("image", "pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime")
        disk_gb = request.data.get("disk", 50)
        onstart = request.data.get("onstart", "")
        env = request.data.get("env", {})

        if not bundle_id:
            return Response(
                {"detail": "bundle_id가 필요합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # REST API 직접 호출
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.VAST_API_KEY}",
            }

            payload = {
                "client_id": "me",
                "image": image,
                "disk": disk_gb,
                "onstart": onstart,
                "env": env,
            }

            resp = requests.put(
                f"{VAST_API_BASE}/asks/{bundle_id}/",
                headers=headers,
                json=payload,
                timeout=60,
            )

            if not resp.ok:
                return Response(
                    {"detail": f"Vast.ai API 오류: {resp.status_code} - {resp.text}"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            result = resp.json() if resp.text else {}
            instance_id = result.get("new_contract") or result.get("id") or result.get("instance_id")

            if not instance_id:
                return Response(
                    {"detail": f"인스턴스 생성 응답 오류: {result}"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            return Response({
                "id": instance_id,
                "status": "starting",
            })

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            return Response(
                {"detail": f"인스턴스 생성 실패: {str(e)}", "traceback": tb},
                status=status.HTTP_502_BAD_GATEWAY,
            )


@extend_schema(tags=["GPU"])
class InstanceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="GPU 인스턴스 조회",
        description="인스턴스 상태와 IP 정보를 조회합니다.",
    )
    def get(self, request, instance_id):
        try:
            client = get_vast_client()
            result = client.show_instances()

            if isinstance(result, str):
                result = json.loads(result)

            instances = result if isinstance(result, list) else result.get("instances", [])

            for inst in instances:
                if str(inst.get("id")) == str(instance_id):
                    return Response({
                        "id": inst.get("id"),
                        "status": inst.get("actual_status", "unknown"),
                        "public_ip": inst.get("public_ipaddr"),
                        "ports": inst.get("ports", {}),
                    })

            return Response(
                {"detail": "인스턴스를 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            return Response(
                {"detail": f"인스턴스 조회 실패: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    @extend_schema(
        summary="GPU 인스턴스 종료",
        description="인스턴스를 완전히 삭제합니다.",
    )
    def delete(self, request, instance_id):
        try:
            client = get_vast_client()
            client.destroy_instance(ID=instance_id)
            return Response({"detail": "인스턴스가 종료되었습니다."})

        except Exception as e:
            return Response(
                {"detail": f"인스턴스 종료 실패: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
