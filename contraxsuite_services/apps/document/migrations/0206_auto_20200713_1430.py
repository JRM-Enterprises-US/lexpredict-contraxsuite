# Generated by Django 2.2.13 on 2020-07-13 14:30

import apps.document.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0205_add_dock_page'),
    ]

    operations = [
        migrations.AlterField(
            model_name='documentfield',
            name='display_yes_no',
            field=models.BooleanField(default=False, help_text='Checking this box will \n    display “Yes” if Related Info text is found, and display “No” if no text is found.'),
        ),
    ]
