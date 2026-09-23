from django.contrib import admin
from .models import Task, Team, Proposal, Account
admin.site.register([Task, Team, Proposal])


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ['user', 'role']
    list_filter = ['role']
    search_fields = ['user__username']
