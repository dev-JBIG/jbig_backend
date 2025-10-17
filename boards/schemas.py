from drf_spectacular.utils import extend_schema, OpenApiParameter

# ===================================================================
# Category Schemas
# ===================================================================
category_viewset_schema = {
    'list': extend_schema(
        summary="[Category] 목록 조회",
        description="모든 게시판 카테고리의 목록을 반환합니다.",
        tags=["Category"]
    ),
    'retrieve': extend_schema(
        summary="[Category] 상세 조회",
        description="ID를 사용하여 특정 카테고리의 상세 정보를 반환합니다.",
        tags=["Category"]
    ),
    'create': extend_schema(
        summary="[Category] 생성 (관리자)",
        description="새로운 게시판 카테고리를 생성합니다. 관리자 권한이 필요합니다.",
        tags=["Category"]
    ),
    'update': extend_schema(
        summary="[Category] 수정 (관리자)",
        description="기존 카테고리의 정보를 수정합니다. 관리자 권한이 필요합니다.",
        tags=["Category"]
    ),
    'partial_update': extend_schema(
        summary="[Category] 부분 수정 (관리자)",
        description="기존 카테고리 정보의 일부를 수정합니다. 관리자 권한이 필요합니다.",
        tags=["Category"]
    ),
    'destroy': extend_schema(
        summary="[Category] 삭제 (관리자)",
        description="특정 카테고리를 삭제합니다. 관리자 권한이 필요합니다.",
        tags=["Category"]
    ),
}

# ===================================================================
# Board Schemas
# ===================================================================
board_viewset_schema = {
    'list': extend_schema(
        summary="[Board] 목록 조회",
        description="모든 게시판의 목록을 반환합니다.",
        tags=["Board"]
    ),
    'retrieve': extend_schema(
        summary="[Board] 상세 조회",
        description="ID를 사용하여 특정 게시판의 상세 정보를 반환합니다.",
        tags=["Board"]
    ),
    'create': extend_schema(
        summary="[Board] 생성 (관리자)",
        description="새로운 게시판을 생성합니다. 관리자 권한이 필요합니다.",
        tags=["Board"]
    ),
    'update': extend_schema(
        summary="[Board] 수정 (관리자)",
        description="기존 게시판의 정보를 수정합니다. 관리자 권한이 필요합니다.",
        tags=["Board"]
    ),
    'partial_update': extend_schema(
        summary="[Board] 부분 수정 (관리자)",
        description="기존 게시판 정보의 일부를 수정합니다. 관리자 권한이 필요합니다.",
        tags=["Board"]
    ),
    'destroy': extend_schema(
        summary="[Board] 삭제 (관리자)",
        description="특정 게시판을 삭제합니다. 관리자 권한이 필요합니다.",
        tags=["Board"]
    ),
    'list_posts': extend_schema(
        summary="[Board] 게시글 목록 조회",
        description="특정 게시판에 속한 모든 게시글의 목록을 반환합니다.",
        tags=["Board"]
    ),
}

board_list_schema = extend_schema(
    summary="[Category] 전체 목록 조회 (게시판 포함)",
    description="모든 카테고리와 각 카테고리에 속한 게시판 목록을 반환합니다.",
    tags=["Category"],
    responses={
        200: {
            'description': '성공',
            'examples': {
                'application/json': [
                    {
                        "category": "공지",
                        "boards": ["공지사항", "이벤트 안내"]
                    },
                    {
                        "category": "커뮤니티",
                        "boards": ["자유게시판", "질문게시판", "정보공유", "유머게시판"]
                    }
                ]
            }
        }
    }
)

# ===================================================================
# Post Schemas
# ===================================================================
post_viewset_schema = {
    'list': extend_schema(
        summary="[Post] 전체 목록 조회",
        description="모든 게시판의 게시글 목록을 반환합니다.",
        tags=["Post"]
    ),
    'retrieve': extend_schema(
        summary="[Post] 상세 조회",
        description="ID를 사용하여 특정 게시글의 상세 정보를 조회합니다. 조회 시 조회수가 1 증가합니다.",
        tags=["Post"]
    ),
    'create': extend_schema(
        summary="[Post] 생성",
        description="새로운 게시글을 작성합니다. 인증된 사용자만 가능합니다.",
        tags=["Post"]
    ),
    'update': extend_schema(
        summary="[Post] 수정",
        description="기존 게시글을 수정합니다. 작성자만 가능합니다.",
        tags=["Post"]
    ),
    'partial_update': extend_schema(
        summary="[Post] 부분 수정",
        description="기존 게시글의 일부를 수정합니다. 작성자만 가능합니다.",
        tags=["Post"]
    ),
    'destroy': extend_schema(
        summary="[Post] 삭제",
        description="특정 게시글을 삭제합니다. 작성자만 가능합니다.",
        tags=["Post"]
    ),
    'like': extend_schema(
        summary="[Post] 좋아요/취소",
        description="특정 게시글에 대해 '좋아요'를 누르거나 취소합니다. 인증된 사용자만 가능합니다.",
        tags=["Post"]
    ),
}

# ===================================================================
# Comment Schemas
# ===================================================================
comment_viewset_schema = {
    'list': extend_schema(
        summary="[Comment] 목록 조회",
        description="특정 게시글의 최상위 댓글 목록을 조회합니다.",
        parameters=[
            OpenApiParameter(name='post_id', description='댓글을 조회할 게시글의 ID', required=True, type=int),
        ],
        tags=["Comment"]
    ),
    'retrieve': extend_schema(
        summary="[Comment] 상세 조회",
        description="ID를 사용하여 특정 댓글(답글 포함)의 상세 정보를 조회합니다.",
        tags=["Comment"]
    ),
    'create': extend_schema(
        summary="[Comment] 생성",
        description="""
        새로운 댓글이나 답글을 작성합니다.
        - 댓글 작성: `post_id`와 `content`를 전달합니다.
        - 답글 작성: `post_id`, `content`, `parent` (부모 댓글 ID)를 전달합니다.
        """,
        tags=["Comment"]
    ),
    'update': extend_schema(
        summary="[Comment] 수정",
        description="기존 댓글이나 답글을 수정합니다. 작성자만 가능합니다.",
        tags=["Comment"]
    ),
    'partial_update': extend_schema(
        summary="[Comment] 부분 수정",
        description="기존 댓글이나 답글의 일부를 수정합니다. 작성자만 가능합니다.",
        tags=["Comment"]
    ),
    'destroy': extend_schema(
        summary="[Comment] 삭제",
        description="특정 댓글이나 답글을 삭제합니다. 작성자만 가능합니다.",
        tags=["Comment"]
    ),
}

# ===================================================================
# Attachment Schemas
# ===================================================================
attachment_viewset_schema = {
    'list': extend_schema(
        summary="[Attachment] 목록 조회",
        description="업로드된 모든 파일의 목록을 반환합니다.",
        tags=["Attachment"]
    ),
    'retrieve': extend_schema(
        summary="[Attachment] 상세 조회",
        description="ID를 사용하여 특정 파일의 상세 정보를 반환합니다.",
        tags=["Attachment"]
    ),
    'create': extend_schema(
        summary="[Attachment] 생성",
        description="하나 이상의 파일을 서버에 업로드하고 파일 정보를 반환합니다.",
        tags=["Attachment"]
    ),
    'destroy': extend_schema(
        summary="[Attachment] 삭제",
        description="ID를 사용하여 특정 파일을 삭제합니다.",
        tags=["Attachment"]
    ),
}
