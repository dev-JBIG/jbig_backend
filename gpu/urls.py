from django.urls import path
from .views import OfferListView, InstanceView, InstanceDetailView

urlpatterns = [
    path('offers', OfferListView.as_view(), name='gpu-offers'),
    path('instances', InstanceView.as_view(), name='gpu-instance-create'),
    path('instances/<str:instance_id>', InstanceDetailView.as_view(), name='gpu-instance-detail'),
]
