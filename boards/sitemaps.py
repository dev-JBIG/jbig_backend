"""검색엔진용 동적 사이트맵.

프론트엔드(CSR SPA)의 실제 페이지 URL을 나열한다.
- 정적 페이지: 홈('/')
- 게시글 상세: '/board/{board_id}/{post_id}'  (프론트 라우트 board/:boardId/:id 와 일치)

게시글 포함 기준은 views._is_publicly_previewable 과 동일하게 맞춘다:
- board.read_permission == 'all'
- post_type == DEFAULT
- board.board_type != JUSTIFICATION_LETTER

도메인은 요청 호스트(jbig.co.kr)를 사용하므로 django.contrib.sites 설정이 필요 없다.
"""
from django.contrib.sitemaps import Sitemap

from .models import Post, Board


class StaticSitemap(Sitemap):
    changefreq = "weekly"
    priority = 1.0
    protocol = "https"

    def items(self):
        return ["/"]

    def location(self, item):
        return item


class PostSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7
    protocol = "https"
    limit = 5000

    def items(self):
        return (
            Post.objects
            .filter(post_type=Post.PostType.DEFAULT, board__read_permission="all")
            .exclude(board__board_type=Board.BoardType.JUSTIFICATION_LETTER)
            .select_related("board")
            .order_by("-created_at")
        )

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return f"/board/{obj.board_id}/{obj.id}"
