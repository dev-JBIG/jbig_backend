from django.urls import path
from .views import (
    RecruitmentListAPIView,
    RecruitmentDetailAPIView,
    RecruitmentStatusAPIView,
    ApplyAPIView,
    MyApplicationAPIView,
    ApplicationListAPIView,
    AcceptRejectApplicationAPIView,
    MyRecruitmentsAPIView,
    MyApplicationsAPIView,
)

urlpatterns = [
    # 모집 목록 & 내 모집/지원
    path('recruitments/', RecruitmentListAPIView.as_view(), name='recruitment-list'),
    path('recruitments/my-recruitments/', MyRecruitmentsAPIView.as_view(), name='my-recruitments'),
    path('recruitments/my-applications/', MyApplicationsAPIView.as_view(), name='my-applications'),

    # 모집 상세 & 수정
    path('recruitments/<int:post_id>/', RecruitmentDetailAPIView.as_view(), name='recruitment-detail'),

    # 모집 상태 변경
    path('recruitments/<int:post_id>/close/', RecruitmentStatusAPIView.as_view(), {'action': 'close'}, name='recruitment-close'),
    path('recruitments/<int:post_id>/reopen/', RecruitmentStatusAPIView.as_view(), {'action': 'reopen'}, name='recruitment-reopen'),
    path('recruitments/<int:post_id>/complete/', RecruitmentStatusAPIView.as_view(), {'action': 'complete'}, name='recruitment-complete'),
    path('recruitments/<int:post_id>/cancel/', RecruitmentStatusAPIView.as_view(), {'action': 'cancel'}, name='recruitment-cancel'),

    # 지원
    path('recruitments/<int:post_id>/apply/', ApplyAPIView.as_view(), name='recruitment-apply'),
    path('recruitments/<int:post_id>/my-application/', MyApplicationAPIView.as_view(), name='my-application'),
    path('recruitments/<int:post_id>/applications/', ApplicationListAPIView.as_view(), name='application-list'),
    path('recruitments/<int:post_id>/applications/<int:app_id>/accept/', AcceptRejectApplicationAPIView.as_view(), {'action': 'accept'}, name='application-accept'),
    path('recruitments/<int:post_id>/applications/<int:app_id>/reject/', AcceptRejectApplicationAPIView.as_view(), {'action': 'reject'}, name='application-reject'),
]
