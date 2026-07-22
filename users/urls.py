from django.urls import path

from . import views

app_name = 'users'

urlpatterns = [
    path('signup/', views.signup_view, name='signup'),
    path('signin/', views.signin_view, name='signin'),
    path('signout/', views.signout_view, name='signout'),
    path('auth/google/', views.google_auth_view, name='google_auth'),
    path('complete-profile/', views.complete_profile_view, name='complete_profile'),
    path('profile/', views.profile_view, name='profile'),
]
