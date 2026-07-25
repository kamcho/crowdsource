from django.urls import path

from . import views

app_name = 'home'

urlpatterns = [
    path('', views.landing, name='landing'),
    path('products/', views.product_browse, name='product_browse'),
    path('products/load/', views.product_browse_load, name='product_browse_load'),
    path('privacy/', views.privacy_policy, name='privacy_policy'),
]
