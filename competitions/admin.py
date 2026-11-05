from django.contrib import admin

from .models import Competition, DatasetVersion, FinalResult, Participant, Submission


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'state', 'starts_at', 'ends_at', 'dataset']
    readonly_fields = ['finalized_at']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DatasetVersion)
class DatasetVersionAdmin(ReadOnlyAdmin):
    list_display = ['version', 'test_rows', 'public_rows', 'private_rows', 'evaluator_version']


@admin.register(Participant)
class ParticipantAdmin(ReadOnlyAdmin):
    list_display = ['public_name', 'user', 'is_test', 'selected_submission_id']
    search_fields = ['user__email', 'user__username']


@admin.register(Submission)
class SubmissionAdmin(ReadOnlyAdmin):
    list_display = ['id', 'participant', 'filename', 'accepted_at', 'status', 'public_rmse', 'attempts']
    list_filter = ['status', 'participant__is_test']
    exclude = ['private_rmse', 'worker_token', 'content_hash', 'request_key']


@admin.register(FinalResult)
class FinalResultAdmin(ReadOnlyAdmin):
    list_display = ['rank', 'public_name', 'private_rmse', 'submission', 'selection_reason']
