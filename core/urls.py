from django.urls import path

from . import product_import_views
from . import views

app_name = 'core'

urlpatterns = [
    path('dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/create/', views.supplier_create, name='supplier_create'),
    path('suppliers/<int:supplier_id>/', views.supplier_manage, name='supplier_manage'),
    path('suppliers/<int:supplier_id>/edit/', views.supplier_edit, name='supplier_edit'),
    path('categories/', views.category_list, name='category_list'),
    path('categories/create/', views.category_create, name='category_create'),
    path('products/', views.product_list, name='product_list'),
    path('products/create/', views.product_create, name='product_create'),
    path('products/import/', product_import_views.product_import_list, name='product_import_list'),
    path('products/import/new/', product_import_views.product_import_start, name='product_import_start'),
    path('products/import/<int:draft_id>/supplier/', product_import_views.product_import_supplier, name='product_import_supplier'),
    path('products/import/<int:draft_id>/categories/', product_import_views.product_import_categories, name='product_import_categories'),
    path('products/import/<int:draft_id>/basics/', product_import_views.product_import_basics, name='product_import_basics'),
    path('products/import/<int:draft_id>/attributes/', product_import_views.product_import_attributes, name='product_import_attributes'),
    path('products/import/<int:draft_id>/variations/', product_import_views.product_import_variations, name='product_import_variations'),
    path('products/import/<int:draft_id>/product-media/', product_import_views.product_import_product_media, name='product_import_product_media'),
    path('products/import/<int:draft_id>/variation-media/', product_import_views.product_import_variation_media, name='product_import_variation_media'),
    path('products/import/<int:draft_id>/review/', product_import_views.product_import_review, name='product_import_review'),
    path('products/import/<int:draft_id>/discard/', product_import_views.product_import_discard, name='product_import_discard'),
    path('products/<int:product_id>/options/', views.product_option_list, name='product_option_list'),
    path('products/<int:product_id>/options/create/', views.product_option_create, name='product_option_create'),
    path('options/<int:option_id>/values/', views.product_option_value_list, name='product_option_value_list'),
    path('options/<int:option_id>/values/create/', views.product_option_value_create, name='product_option_value_create'),
    path('products/<int:product_id>/variations/', views.product_variation_list, name='product_variation_list'),
    path('products/<int:product_id>/variations/create/', views.product_variation_create, name='product_variation_create'),
    path('products/<int:product_id>/variations/<int:variation_id>/files/', views.product_variation_files, name='product_variation_files'),
    path('products/<int:product_id>/attributes/', views.product_attribute_list, name='product_attribute_list'),
    path('products/<int:product_id>/attributes/create/', views.product_attribute_create, name='product_attribute_create'),
    path('group-buys/', views.group_buy_list, name='group_buy_list'),
    path('group-buys/create/', views.group_buy_create, name='group_buy_create'),
    path('group-buys/<int:group_buy_id>/', views.group_buy_manage, name='group_buy_manage'),
    path('refunds/', views.refund_list, name='refund_list'),
    path('complaints/', views.complaint_list, name='complaint_list'),
]
