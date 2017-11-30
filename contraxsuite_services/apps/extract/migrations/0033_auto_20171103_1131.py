# -*- coding: utf-8 -*-
# Generated by Django 1.11.3 on 2017-11-03 11:31
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0003_auto_20170818_0632'),
        ('extract', '0032_auto_20171031_1610'),
    ]

    operations = [
        migrations.CreateModel(
            name='CopyrightUsage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('count', models.IntegerField(default=0)),
                ('year', models.CharField(blank=True, db_index=True, max_length=10, null=True)),
                ('name', models.CharField(db_index=True, max_length=200)),
                ('copyright_str', models.CharField(max_length=200)),
                ('text_unit', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='document.TextUnit')),
            ],
            options={
                'ordering': ('text_unit', '-count', 'name'),
            },
        ),
        migrations.AlterUniqueTogether(
            name='copyrightusage',
            unique_together=set([('text_unit', 'name', 'year')]),
        ),
    ]
