# Generated by Django 2.2.4 on 2019-11-13 18:25

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('task', '0050_task_run_after_sub_tasks_failed'),
    ]

    operations = [
        migrations.RenameField(
            model_name='task',
            old_name='run_after_sub_tasks_failed',
            new_name='run_if_main_task_failed',
        ),
    ]
