from django.db.models import F
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Application, Recruitment


@receiver(post_delete, sender=Application)
def update_accepted_count_on_delete(sender, instance, **kwargs):
    """지원이 삭제될 때 (철회 또는 유저 탈퇴) accepted_count 조정"""
    if instance.status == Application.Status.ACCEPTED:
        Recruitment.objects.filter(
            pk=instance.recruitment_id,
            accepted_count__gt=0,
        ).update(accepted_count=F('accepted_count') - 1)
