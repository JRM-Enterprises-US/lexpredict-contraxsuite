# Generated by Django 2.2.4 on 2020-01-15 08:29

from django.db import migrations, connection


def do_migrate(apps, schema_editor):

    with connection.cursor() as cursor:
        cursor.execute(
            'UPDATE document_fieldannotation dfa SET assignee_id=dd.assignee_id, assign_date=dd.assign_date FROM document_document dd WHERE dfa.document_id=dd.id and dd.assignee_id is not null;')

    FieldAnnotation = apps.get_model('document', 'FieldAnnotation')
    FieldAnnotationStatus = apps.get_model('document', 'FieldAnnotationStatus')
    FieldAnnotation.objects.filter(document__status__code='completed').update(
        status=FieldAnnotationStatus.objects.filter(is_confirm=True).first())


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0175_auto_20200115_0828'),
    ]

    operations = [
        migrations.RunPython(do_migrate, reverse_code=migrations.RunPython.noop),
    ]
