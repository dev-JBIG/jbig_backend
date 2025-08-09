from rest_framework import permissions

class IsVerified(permissions.BasePermission):
    """
    Allows access only to verified users.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_verified

class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    객체의 소유자에게만 쓰기 권한을 부여하는 커스텀 권한.
    """
    def has_object_permission(self, request, view, obj):
        # 읽기 권한은 모두에게 허용 (GET, HEAD, OPTIONS)
        if request.method in permissions.SAFE_METHODS:
            return True

        # 쓰기 권한은 객체의 소유자에게만 허용
        return obj.author == request.user
