"""
    Copyright (C) 2017, ContraxSuite, LLC

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as
    published by the Free Software Foundation, either version 3 of the
    License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

    You can also be released from the requirements of the license by purchasing
    a commercial license from ContraxSuite, LLC. Buying such a license is
    mandatory as soon as you develop commercial activities involving ContraxSuite
    software without disclosing the source code of your own applications.  These
    activities include: offering paid services to customers as an ASP or "cloud"
    provider, processing documents on the fly in a web application,
    or shipping ContraxSuite within a closed source product.
"""
# -*- coding: utf-8 -*-

from typing import Dict

from django.conf import settings
from django.conf.urls import url
from django.http import JsonResponse
from rest_framework import views

import settings
from apps.document.field_types import FIELD_TYPES_REGISTRY
from apps.document.models import Document, DocumentField, DocumentFieldValue


def _to_dto(field_value: DocumentFieldValue):
    return {
        'id': field_value.pk,
        'document_id': field_value.document_id,
        'ranges': [{
            'start': '/p[1]',
            'end': '/p[1]',
            'startOffset': field_value.location_start,
            'endOffset': field_value.location_end
        }],
        'quote': field_value.location_text,
        'text': None,
        'user_id': field_value.modified_by_id or field_value.created_by_id,
        'value': field_value.value,
        'field_id': field_value.field_id
    }


class DocumentAnnotationStorageSearchView(views.APIView):
    def get(self, request, *args, **kwargs):
        """
        Get all annotations made for the specified document and field.

        GET params:
          - document_id: int PK of the document.

        Returns annotations in JSON acceptable by annotator.js.

        """
        document_id = request.GET.get('document_id')

        field_values = DocumentFieldValue.objects.filter(document_id=document_id)

        return JsonResponse({'rows': [_to_dto(a) for a in field_values]})


def _trigger_retraining_model(document):
    if settings.ANNOTATOR_RETRAIN_MODEL_ON_ANNOTATIONS_CHANGE:
        print('TODO: Trigger partial retraining model on annotation change')


def _save_annotation(annotator_data: Dict, user, field_value_id=None) -> Dict:
    """
            Add a new annotation / document field value.
            Accepts JSON structure generated by annotator.js.

            """
    doc = Document.objects.get(pk=annotator_data['document_id'])
    document_field = DocumentField.objects.get(pk=annotator_data.get('field_id'))
    value = annotator_data.get('value')
    selection_range = annotator_data['ranges'][0]
    location_start = selection_range['startOffset']
    location_end = selection_range['endOffset']
    location_text = doc.full_text[location_start:location_end]

    field_type = FIELD_TYPES_REGISTRY.get(document_field.type)

    if field_value_id:
        field_value = DocumentFieldValue.objects.get(pk=field_value_id)
        field_value = field_type.update(field_value,
                                        doc,
                                        document_field,
                                        location_start,
                                        location_end,
                                        location_text,
                                        value,
                                        user)
    else:
        field_value = field_type.save_value(doc,
                                            document_field,
                                            location_start,
                                            location_end,
                                            location_text,
                                            value,
                                            user,
                                            True)

    _trigger_retraining_model(doc)

    return _to_dto(field_value)


class DocumentAnnotationsView(views.APIView):
    def post(self, request, *args, **kwargs):
        return JsonResponse(_save_annotation(request.data, request.user))


class DocumentAnnotationView(views.APIView):
    def get(self, request, *args, pk):
        return JsonResponse(_to_dto(DocumentFieldValue.objects.get(pk=pk)))

    def post(self, request, *args, **kwargs):
        return JsonResponse(_save_annotation(request.data, request.user))

    def put(self, request, *args, pk):
        """
        Update an existing annotation. Accepts JSON structure generated by annotator.js.

        """
        return JsonResponse(_save_annotation(request.data, request.user, pk))

    def delete(self, request, *args, pk):
        """
        Delete an annotation.

        """

        field_value = DocumentFieldValue.objects.get(pk=pk)
        doc = field_value.document
        field = field_value.field
        field_type = FIELD_TYPES_REGISTRY.get(field.type)

        field_type.delete(field_value)

        _trigger_retraining_model(doc)
        return JsonResponse(_to_dto(field_value))


urlpatterns = [
    url(
        r'^search$',
        DocumentAnnotationStorageSearchView.as_view(),
        name='annotations_search'
    ),

    url(
        r'^annotations/?$',
        DocumentAnnotationsView.as_view(),
        name='annotations'
    ),
    url(
        r'^annotations/(?P<pk>\d+)$',
        DocumentAnnotationView.as_view(),
        name='annotation'
    ),
]