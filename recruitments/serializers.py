from django.utils import timezone
from rest_framework import serializers
from .models import Recruitment, Application


class RecruitmentCreateSerializer(serializers.ModelSerializer):
    """모집 생성/수정용 시리얼라이저"""
    class Meta:
        model = Recruitment
        fields = [
            'recruitment_type', 'max_members', 'deadline',
            'required_skills', 'contact_info', 'show_applicants'
        ]

    def validate_deadline(self, value):
        if value and value < timezone.now():
            raise serializers.ValidationError('마감일은 현재 시각 이후여야 합니다.')
        return value

    def validate_required_skills(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('기술 목록은 배열이어야 합니다.')
        cleaned = list(dict.fromkeys(s.strip() for s in value if isinstance(s, str) and s.strip()))
        return cleaned


class RecruitmentDetailSerializer(serializers.ModelSerializer):
    """모집 상세 조회용 시리얼라이저 (public)"""
    recruitment_type_display = serializers.CharField(source='get_recruitment_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    has_applied = serializers.SerializerMethodField()
    my_application_status = serializers.SerializerMethodField()
    contact_info = serializers.SerializerMethodField()
    spots_remaining = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    total_applicants = serializers.SerializerMethodField()

    class Meta:
        model = Recruitment
        fields = [
            'recruitment_type', 'recruitment_type_display',
            'status', 'status_display',
            'max_members', 'accepted_count', 'spots_remaining',
            'deadline', 'required_skills',
            'contact_info', 'show_applicants',
            'has_applied', 'my_application_status',
            'is_owner', 'total_applicants',
        ]

    def get_has_applied(self, obj):
        user = self.context['request'].user
        if not user.is_authenticated:
            return False
        return obj.applications.filter(applicant=user).exists()

    def get_my_application_status(self, obj):
        user = self.context['request'].user
        if not user.is_authenticated:
            return None
        app = obj.applications.filter(applicant=user).first()
        return app.status if app else None

    def get_contact_info(self, obj):
        user = self.context['request'].user
        if not user.is_authenticated:
            return None
        # 모집자/관리자는 항상 볼 수 있음
        if obj.post.author == user or user.is_staff:
            return obj.contact_info
        # 수락된 지원자만 볼 수 있음
        if obj.applications.filter(applicant=user, status=Application.Status.ACCEPTED).exists():
            return obj.contact_info
        return None

    def get_spots_remaining(self, obj):
        if obj.max_members == 0:
            return None  # 무제한
        return max(0, obj.max_members - obj.accepted_count)

    def get_is_owner(self, obj):
        user = self.context['request'].user
        if not user.is_authenticated:
            return False
        return obj.post.author == user or user.is_staff

    def get_total_applicants(self, obj):
        """모집자에게만 전체 지원자 수 공개"""
        user = self.context['request'].user
        if user.is_authenticated and (obj.post.author == user or user.is_staff):
            return obj.applications.count()
        return None


class RecruitmentListSerializer(serializers.ModelSerializer):
    """모집 목록용 시리얼라이저 (PostList에 포함)"""
    recruitment_type_display = serializers.CharField(source='get_recruitment_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    spots_remaining = serializers.SerializerMethodField()

    class Meta:
        model = Recruitment
        fields = [
            'recruitment_type', 'recruitment_type_display',
            'status', 'status_display',
            'max_members', 'accepted_count', 'spots_remaining',
            'deadline',
        ]

    def get_spots_remaining(self, obj):
        if obj.max_members == 0:
            return None
        return max(0, obj.max_members - obj.accepted_count)


class ApplicationCreateSerializer(serializers.ModelSerializer):
    """지원 생성용"""
    class Meta:
        model = Application
        fields = ['message']


class ApplicationFullSerializer(serializers.ModelSerializer):
    """모집자용 — 전체 정보"""
    applicant_name = serializers.SerializerMethodField()
    applicant_username = serializers.SerializerMethodField()
    applicant_semester = serializers.IntegerField(source='applicant.semester', read_only=True)
    applicant_resume = serializers.CharField(source='applicant.resume', read_only=True, default='')
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Application
        fields = [
            'id', 'applicant_name', 'applicant_username', 'applicant_semester', 'applicant_resume',
            'status', 'status_display', 'message', 'recruiter_note',
            'created_at', 'updated_at'
        ]

    def get_applicant_name(self, obj):
        return obj.applicant.username

    def get_applicant_username(self, obj):
        return obj.applicant.email.split('@')[0]


class ApplicationPublicSerializer(serializers.ModelSerializer):
    """다른 지원자용 — 이름, 기수, 상태만 (show_applicants=True일 때)"""
    applicant_name = serializers.SerializerMethodField()
    applicant_semester = serializers.IntegerField(source='applicant.semester', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Application
        fields = ['id', 'applicant_name', 'applicant_semester', 'status', 'status_display']

    def get_applicant_name(self, obj):
        return obj.applicant.username


class ApplicationOwnSerializer(serializers.ModelSerializer):
    """지원자 본인용"""
    applicant_name = serializers.SerializerMethodField()
    applicant_semester = serializers.IntegerField(source='applicant.semester', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Application
        fields = [
            'id', 'applicant_name', 'applicant_semester',
            'status', 'status_display', 'message', 'created_at'
        ]

    def get_applicant_name(self, obj):
        return obj.applicant.username


class MyApplicationSerializer(serializers.ModelSerializer):
    """마이페이지 - 내 지원 목록"""
    post_id = serializers.IntegerField(source='recruitment.post_id', read_only=True)
    post_title = serializers.CharField(source='recruitment.post.title', read_only=True)
    recruitment_type = serializers.IntegerField(source='recruitment.recruitment_type', read_only=True)
    recruitment_type_display = serializers.CharField(source='recruitment.get_recruitment_type_display', read_only=True)
    recruitment_status = serializers.IntegerField(source='recruitment.status', read_only=True)
    board_id = serializers.IntegerField(source='recruitment.post.board_id', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Application
        fields = [
            'id', 'post_id', 'post_title', 'board_id',
            'recruitment_type', 'recruitment_type_display',
            'recruitment_status',
            'status', 'status_display', 'created_at'
        ]
