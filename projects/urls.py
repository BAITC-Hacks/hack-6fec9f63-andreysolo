from django.urls import path
from . import views

urlpatterns = [path('', views.catalog, name='catalog'), path('workspace/', views.workspace, name='workspace'), path('tasks/new/', views.create, name='create'), path('tasks/<int:pk>/', views.detail, name='detail'), path('tasks/<int:pk>/edit/', views.edit, name='edit'), path('tasks/<int:pk>/publish/', views.publish, name='publish'), path('tasks/<int:pk>/propose/', views.propose, name='propose'), path('proposals/<int:pk>/decide/', views.decide, name='decide'), path('proposals/<int:pk>/evidence/', views.evidence, name='evidence')]
