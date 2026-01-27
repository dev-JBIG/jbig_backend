from rest_framework import permissions
from boards.models import Board, Post
import logging

logger = logging.getLogger(__name__)

class DebugPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        logger.warning(f"Request Headers: {request.headers}")
        logger.warning(f"Request User: {request.user}")
        logger.warning(f"Is Authenticated: {request.user.is_authenticated}")
        return True

class IsBoardReadable(permissions.BasePermission):
    """
    Allows access based on the board's `read_permission` field.
    - 'all': Anyone can read (including non-authenticated users).
    - 'staff': Only staff members can read.
    """
    def has_permission(self, request, view):
        board = None
        obj = None
        # In PostListCreateAPIView, get_object() is overridden to return the board.
        if hasattr(view, 'get_object'):
            obj = view.get_object()
            if isinstance(obj, Board):
                board = obj
            # For detail views, the object is a Post, so we get its board.
            elif hasattr(obj, 'board'):
                board = obj.board
        
        if not board:
            return False

        # If the post is a justification letter, bypass board-level read permission.
        # The PostDetailPermission will handle the fine-grained check.
        if isinstance(obj, Post) and obj.post_type == Post.PostType.JUSTIFICATION_LETTER:
            return True

        read_perm = getattr(board, 'read_permission', 'staff')

        if read_perm == 'all':
            # 'all' 권한인 경우 비로그인 사용자도 접근 가능
            return True
        
        return request.user.is_authenticated and request.user.is_staff

class IsPostWritable(permissions.BasePermission):
    """
    Allows access based on the board's `post_permission` field.
    - 'all': Any authenticated user can write.
    - 'staff': Only staff members can write.
    """
    def has_permission(self, request, view):
        board = None
        if hasattr(view, 'get_object'):
            obj = view.get_object()
            if isinstance(obj, Board):
                board = obj
            elif hasattr(obj, 'board'):
                board = obj.board

        if not board:
            return False

        # Renamed from write_permission in migration 0006
        post_perm = getattr(board, 'post_permission', 'staff')

        if not request.user.is_authenticated:
            return False

        if post_perm == 'all':
            return True
        
        return request.user.is_staff

class IsCommentWritable(permissions.BasePermission):
    """
    Allows access based on the board's `comment_permission` field.
    - 'all': Anyone (including non-authenticated users) can comment.
    - 'staff': Only staff members can comment.
    """
    def has_permission(self, request, view):
        post_id = view.kwargs.get('post_id')
        if not post_id:
            return False
        
        try:
            post = Post.objects.get(pk=post_id)
            board = post.board
        except Post.DoesNotExist:
            return False

        comment_perm = getattr(board, 'comment_permission', 'staff')

        # 'all' 권한인 경우 비회원도 댓글 작성 가능
        if comment_perm == 'all':
            return True
        
        # 'staff' 권한인 경우 스태프만 작성 가능
        return request.user.is_authenticated and request.user.is_staff

class PostDetailPermission(permissions.BasePermission):
    """
    Object-level permission for post detail view.
    Checks post.post_type to determine readability for SAFE_METHODS.
    For other methods, it checks for ownership.
    """
    def has_object_permission(self, request, view, obj):
        # Handle READ permissions for safe methods (GET, HEAD, OPTIONS)
        if request.method in permissions.SAFE_METHODS:
            if obj.post_type == Post.PostType.JUSTIFICATION_LETTER:
                return request.user.is_authenticated and (obj.author.id == request.user.id or request.user.is_staff)

            return True # For DEFAULT and STAFF_ONLY posts, allow read

        # Handle WRITE permissions (PUT, PATCH, DELETE)
        if not request.user.is_authenticated:
            return False

        if hasattr(obj, 'author'):
            return obj.author == request.user or request.user.is_staff
            
        return False

class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Object-level permission to allow only owners of an object to edit it.
    Assumes the model instance has an `author` attribute.
    Applies only for write methods. Staff can also edit.
    """
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        
        if not request.user.is_authenticated:
            return False

        # For posts and comments, the author field exists.
        if hasattr(obj, 'author'):
            # 비회원 댓글(author=None)은 수정/삭제 불가
            if obj.author is None:
                return False
            return obj.author == request.user or request.user.is_staff
        
        return False
