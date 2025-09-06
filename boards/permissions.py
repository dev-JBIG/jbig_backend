from rest_framework import permissions
from boards.models import Board, Post

class IsBoardReadable(permissions.BasePermission):
    """
    Allows access based on the board's `read_permission` field.
    - 'all': Anyone can read.
    - 'staff': Only staff members can read.
    """
    def has_permission(self, request, view):
        board = None
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

        read_perm = getattr(board, 'read_permission', 'staff')

        if read_perm == 'all':
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
    - 'all': Any authenticated user can comment.
    - 'staff': Only staff members can comment.
    """
    def has_permission(self, request, view):
        print(f"--- Inside IsCommentWritable ---")
        post_id = view.kwargs.get('post_id')
        print(f"post_id: {post_id}")
        if not post_id:
            return False
        
        try:
            post = Post.objects.get(pk=post_id)
            board = post.board
            print(f"board: {board.name}, comment_permission: {board.comment_permission}")
        except Post.DoesNotExist:
            print("Post not found")
            return False

        comment_perm = getattr(board, 'comment_permission', 'staff')

        if not request.user.is_authenticated:
            print("User not authenticated")
            return False

        if comment_perm == 'all':
            print("Permission is 'all', returning True")
            return True
        
        print(f"Permission is 'staff', checking if user is staff: {request.user.is_staff}")
        return request.user.is_staff

class PostDetailPermission(permissions.BasePermission):
    """
    Object-level permission for post detail view.
    Checks post.post_type to determine readability.
    """
    def has_object_permission(self, request, view, obj):
        # obj is a Post instance
        if obj.post_type == 2:  # Staff Only
            return request.user.is_authenticated and request.user.is_staff
        
        if obj.post_type == 3:  # Justification Letter
            return request.user.is_authenticated and (obj.author == request.user or request.user.is_staff)

        return True

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
            return obj.author == request.user or request.user.is_staff
        
        return False
