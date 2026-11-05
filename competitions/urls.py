from django.urls import path

from .views import DownloadView, FinalSelectionView, LeaderboardView, OverviewView, SubmissionView, SubmissionsView


urlpatterns = [
    path('', OverviewView.as_view()),
    path('downloads/<str:kind>/', DownloadView.as_view()),
    path('submissions/', SubmissionsView.as_view()),
    path('submissions/<uuid:submission_id>/', SubmissionView.as_view()),
    path('final-selection/', FinalSelectionView.as_view()),
    path('leaderboard/', LeaderboardView.as_view()),
]
