# -*- coding: utf-8 -*-
# Generated by Django 1.11.3 on 2019-02-04 13:01
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('extract', '0039_auto_20190204_1246'),
    ]

    operations = [
        migrations.AlterField(
            model_name='definitionusage',
            name='definition',
            field=models.TextField(),
        ),
        migrations.AlterField(
            model_name='definitionusage',
            name='definition_str',
            field=models.TextField(blank=True, null=True),
        ),
    ]
