from django.db import models
from django.conf import settings


class GpuInstance(models.Model):
    STATUS_CHOICES = [('starting', 'Starting'), ('running', 'Running'), ('terminated', 'Terminated')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='gpu_instances')
    vast_instance_id = models.CharField(max_length=50, unique=True)
    offer_id = models.CharField(max_length=50)
    gpu_name = models.CharField(max_length=100, blank=True)
    hourly_price = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='starting')
    jupyter_token = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    terminated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @classmethod
    def active_count_for_user(cls, user):
        return cls.objects.filter(user=user, status__in=['starting', 'running']).count()
