from django.conf import settings
from django.db import migrations


def assign_roles(apps, schema_editor):
    Account = apps.get_model('projects', 'Account')
    Team = apps.get_model('projects', 'Team')
    Task = apps.get_model('projects', 'Task')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    alias = schema_editor.connection.alias
    students = set(Team.objects.using(alias).values_list('user_id', flat=True))
    owners = set(Task.objects.using(alias).values_list('owner_id', flat=True))
    for user in User.objects.using(alias).all().iterator():
        role = 'student' if user.pk in students else 'business' if user.pk in owners or user.username == 'business' else 'unassigned'
        Account.objects.using(alias).get_or_create(user_id=user.pk, defaults={'role': role})


class Migration(migrations.Migration):
    dependencies = [('projects', '0004_account')]
    operations = [migrations.RunPython(assign_roles, migrations.RunPython.noop)]
