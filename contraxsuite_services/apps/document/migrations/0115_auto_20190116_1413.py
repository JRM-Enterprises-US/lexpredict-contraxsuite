# -*- coding: utf-8 -*-
# Generated by Django 1.11.3 on 2019-01-16 14:13
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0114_documentfield_allow_adding_choices'),
    ]

    operations = [
        migrations.RenameField(
            model_name='documentfield',
            old_name='allow_adding_choices',
            new_name='allow_values_not_specified_in_choices',
        ),
    ]
