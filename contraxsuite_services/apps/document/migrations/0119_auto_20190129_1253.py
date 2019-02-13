# -*- coding: utf-8 -*-
# Generated by Django 1.11.17 on 2019-01-29 12:53
from __future__ import unicode_literals

import apps.common.utils
import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0118_auto_20190125_1551'),
    ]

    operations = [
        migrations.AlterField(
            model_name='document',
            name='field_values',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, encoder=apps.common.utils.CustomDjangoJSONEncoder, null=True),
        ),
        migrations.AlterField(
            model_name='document',
            name='generic_data',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, encoder=apps.common.utils.CustomDjangoJSONEncoder, null=True),
        ),
        migrations.AlterField(
            model_name='document',
            name='metadata',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, encoder=apps.common.utils.CustomDjangoJSONEncoder),
        ),
        migrations.AlterField(
            model_name='historicaldocument',
            name='field_values',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, encoder=apps.common.utils.CustomDjangoJSONEncoder, null=True),
        ),
        migrations.AlterField(
            model_name='historicaldocument',
            name='generic_data',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, encoder=apps.common.utils.CustomDjangoJSONEncoder, null=True),
        ),
        migrations.AlterField(
            model_name='historicaldocument',
            name='metadata',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, encoder=apps.common.utils.CustomDjangoJSONEncoder),
        ),
    ]