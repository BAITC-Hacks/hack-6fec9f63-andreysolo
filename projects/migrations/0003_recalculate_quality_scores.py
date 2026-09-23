from django.db import migrations


def recalculate(apps, schema_editor):
    Task = apps.get_model('projects', 'Task')
    groups = [(('context', 10), ('need', 10)), (('data', 20),), (('result', 15),), (('success', 15),), (('constraints', 10),), (('users', 10),), (('contact', 5), ('interaction', 5))]
    for task in Task.objects.using(schema_editor.connection.alias).all().iterator():
        score = sum(sum(weight * 50 for name, weight in group if getattr(task, name).strip()) // 100 for group in groups) if task.confirmed else 0
        Task.objects.using(schema_editor.connection.alias).filter(pk=task.pk).update(score=score)


class Migration(migrations.Migration):
    dependencies = [('projects', '0002_task_quality_reviews')]
    operations = [migrations.RunPython(recalculate, migrations.RunPython.noop)]
