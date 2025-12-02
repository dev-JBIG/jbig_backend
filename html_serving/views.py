from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema


@extend_schema(
    tags=["Deprecated"],
    summary="[Deprecated] Notion HTML",
    description="This endpoint is deprecated. Notion content is now served via splitbee proxy on frontend.",
    deprecated=True,
)
@api_view(['GET'])
def notion_view(request):
    return Response(
        {"detail": "This endpoint is deprecated. Notion is now served via splitbee proxy."},
        status=status.HTTP_410_GONE
    )


@extend_schema(
    tags=["Deprecated"],
    summary="[Deprecated] Banner Image",
    description="This endpoint is deprecated. Banner is now served via NCP CDN.",
    deprecated=True,
)
@api_view(['GET'])
def banner_view(request):
    return Response(
        {"detail": "This endpoint is deprecated. Use CDN URL: https://kr.object.ncloudstorage.com/jbig/static/banner.jpg"},
        status=status.HTTP_410_GONE
    )
