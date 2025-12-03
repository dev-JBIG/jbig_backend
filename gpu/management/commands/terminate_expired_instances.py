import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from vastai_sdk import VastAI
from gpu.models import GpuInstance

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '만료된 GPU 인스턴스 자동 종료'

    def handle(self, *args, **options):
        now = timezone.now()
        expired = GpuInstance.objects.filter(status__in=['starting', 'running'], expires_at__lt=now)

        if not expired.exists():
            return

        try:
            client = VastAI(api_key=settings.VAST_API_KEY)
        except Exception as e:
            logger.error(f"Vast 클라이언트 실패: {e}")
            return

        for inst in expired:
            try:
                client.destroy_instance(ID=inst.vast_instance_id)
                inst.status, inst.terminated_at = 'terminated', now
                inst.save(update_fields=['status', 'terminated_at'])
                self.stdout.write(self.style.SUCCESS(f'종료: {inst.vast_instance_id}'))
            except Exception as e:
                logger.error(f"종료 실패: {inst.vast_instance_id} - {e}")
