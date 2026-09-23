from django.contrib import admin
from .models import Task, Team, Proposal
admin.site.register([Task, Team, Proposal])
