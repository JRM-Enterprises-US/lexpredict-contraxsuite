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

# Future imports
from __future__ import absolute_import, unicode_literals

# Standard imports
import datetime
import json
import os
import urllib

# Third-party imports
from typing import Optional, List, Tuple

import magic
import pandas as pd
# Django imports
from django.conf import settings
from django.contrib.sites.models import Site
from django.db.models.expressions import Case, When, Value
from django.urls import reverse
from django.db.models import Count, F, Prefetch, Q, BooleanField
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.shortcuts import render
from django.views.generic import DetailView
# Other lib imports
from elasticsearch import Elasticsearch

# Project imports
from apps.analyze.models import (
    DocumentCluster, TextUnitCluster,
    TextUnitClassification, TextUnitClassifierSuggestion)
import apps.common.mixins
from apps.common.file_storage import get_file_storage
from apps.common.utils import cap_words
from apps.document.forms import DetectFieldValuesForm, TrainDocumentFieldDetectorModelForm, TrainAndTestForm, \
    LoadDocumentWithFieldsForm, FindBrokenDocumentFieldValuesForm, ImportCSVFieldDetectionConfigForm, \
    FixDocumentFieldCodesForm, ExportDocumentTypeForm, ImportDocumentTypeForm, IdentifyContractsForm
from apps.document.models import (
    Document, DocumentProperty, DocumentRelation, DocumentNote, DocumentTag,
    TextUnit, TextUnitProperty, TextUnitNote, TextUnitTag)
from apps.document.tasks import ImportCSVFieldDetectionConfig, FindBrokenDocumentFieldValues, ImportDocumentType, \
    FixDocumentFieldCodes, identify_contracts
from apps.dump.app_dump import get_app_config_dump, download
from apps.extract.models import (
    AmountUsage, CitationUsage, CopyrightUsage, Court, CourtUsage, CurrencyUsage,
    DateDurationUsage, DateUsage, DefinitionUsage, DistanceUsage,
    GeoAlias, GeoAliasUsage, GeoEntity, GeoEntityUsage, GeoRelation,
    Party, PartyUsage, PercentUsage,
    RatioUsage, RegulationUsage, Term, TermUsage, TrademarkUsage, UrlUsage)
from apps.project.models import TaskQueue
from apps.project.views import ProjectListView, TaskQueueListView
from apps.task.models import Task
from apps.task.tasks import call_task, call_task_func
from apps.task.views import BaseAjaxTaskView, TaskListView, LoadFixturesView
from apps.users.models import User

__author__ = "ContraxSuite, LLC; LexPredict, LLC"
__copyright__ = "Copyright 2015-2020, ContraxSuite, LLC"
__license__ = "https://github.com/LexPredict/lexpredict-contraxsuite/blob/1.6.0/LICENSE"
__version__ = "1.6.0"
__maintainer__ = "LexPredict, LLC"
__email__ = "support@contraxsuite.com"


from task_names import TASK_NAME_IDENTIFY_CONTRACTS

python_magic = magic.Magic(mime=True)

file_storage = get_file_storage()


def search(request):
    """
    Search dispatcher.
    :param request:
    :return:
    """
    # Check for term redirect
    if request.GET.get("elastic_search", "").strip() or \
            request.GET.get("text_search", "").strip():
        view_name = "document:text-unit-list"

    # Check for term redirect
    elif request.GET.get("term_search", "").strip():
        view_name = "extract:term-usage-list"

    # Check for term redirect
    elif request.GET.get("entity_search", "").strip():
        view_name = "extract:geo-entity-usage-list"

    # Check for term redirect
    elif request.GET.get("party_search", "").strip():
        view_name = "extract:party-usage-list"

    # Redirect others to Document List page
    else:
        view_name = "document:document-list"

    return redirect('{}?{}'.format(reverse(view_name), request.GET.urlencode()))


class DocumentListView(apps.common.mixins.JqPaginatedListView):
    template_name = 'document/document_list.html'
    """DocumentListView

    CBV for list of Document records.
    """
    model = Document
    json_fields = ['project__name',
                   'name', 'document_type__title',
                   'title', 'language',
                   # this field makes DB query significantly longer
                   # 'is_contract',
                   'properties', 'relations', 'paragraphs', 'sentences', 'is_contract']
    limit_reviewers_qs_by_field = ""
    field_types = dict(
        properties=int,
        relations=int,
    )
    has_contracts = None

    def get_queryset(self):
        qs = super().get_queryset()

        qs = qs.filter(project_id__in=self.request.user.userprojectssavedfilter.projects.all())

        document_text_search = self.request.GET.get("document_text_search")
        if document_text_search:
            document_ids = TextUnit.objects.filter(textunittext__text__full_text_search=document_text_search)\
                .values_list('document_id', flat=True)\
                .distinct()
            qs = qs.filter(id__in=document_ids)

        description_search = self.request.GET.get("description_search")
        if description_search:
            qs = qs.filter(description__icontains=description_search)

        name_search = self.request.GET.get("name_search")
        if name_search:
            qs = qs.filter(name__icontains=name_search)

        language_search = self.request.GET.get("language_search")
        if language_search:
            qs = qs.filter(language__icontains=language_search)

        if 'party_pk' in self.request.GET:
            qs = qs.filter(textunit__partyusage__party__pk=self.request.GET['party_pk'])

        # Populate with child counts
        qs = qs.annotate(
            # this field makes DB query significantly longer
            # is_contract=KeyTextTransform('is_contract', 'metadata'),
            properties=Count('documentproperty', distinct=True),
            num_relation_a=Count('document_a_set', distinct=True),
            num_relation_b=Count('document_b_set', distinct=True),
        ).annotate(relations=F('num_relation_a') + F('num_relation_b'),
                   is_contract=Case(When(document_class='CONTRACT', then=Value(True)),
                                    default=Value(False),
                                    output_field=BooleanField()))

        self.has_contracts = qs.filter(document_class='CONTRACT').exists()

        return qs

    def get_json_data(self, **kwargs):
        data = super().get_json_data()
        for item in data['data']:
            item['url'] = self.full_reverse('document:document-detail', args=[item['pk']])
        data['has_contracts'] = self.has_contracts
        return data

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data()
        params = dict(urllib.parse.parse_qsl(self.request.GET.urlencode()))
        ctx.update(params)
        return ctx


class DocumentPropertyCreateView(apps.common.mixins.CustomCreateView):
    """DocumentListView

    CBV for list of Document records.
    """
    model = DocumentProperty
    fields = ('document', 'key', 'value')

    def has_permission(self):
        if self.kwargs.get('pk'):
            document = get_object_or_404(Document, pk=self.kwargs['pk'])
            return self.request.user.can_view_document(document)
        return True

    def get_initial(self):
        initial = super().get_initial()
        if not self.object and self.kwargs.get('pk'):
            initial['document'] = Document.objects.get(pk=self.kwargs['pk'])
        return initial

    def get_success_url(self):
        return self.request.POST.get('next') or reverse('document:document-property-list')


class DocumentPropertyUpdateView(DocumentPropertyCreateView, apps.common.mixins.CustomUpdateView):
    def has_permission(self):
        document = self.get_object().document
        return self.request.user.can_view_document(document)


class DocumentPropertyListView(apps.common.mixins.JqPaginatedListView):
    model = DocumentProperty
    limit_reviewers_qs_by_field = 'document'
    json_fields = ['key', 'value',
                   'created_date', 'created_by__username',
                   'modified_date', 'modified_by__username',
                   'document__pk',
                   'document__project__name',
                   'document__name',
                   'document__document_type__title', 'document__description']
    template_name = 'document/document_property_list.html'

    def get_queryset(self):
        qs = super().get_queryset().order_by('document_id', 'key')
        if "document_pk" in self.request.GET:
            qs = qs.filter(document__pk=self.request.GET['document_pk'])

        qs = qs.filter(document__project_id__in=self.request.user.userprojectssavedfilter.projects.all())

        key_search = self.request.GET.get('key_search')
        if key_search:
            qs = qs.filter(key__icontains=key_search)
        qs = qs.select_related('document')
        return qs

    def get_json_data(self, **kwargs):
        data = super().get_json_data()
        for item in data['data']:
            item['url'] = self.full_reverse('document:document-detail', args=[item['document__pk']])
            item['edit_url'] = self.full_reverse('document:document-property-update', args=[item['pk']])
            item['delete_url'] = self.full_reverse('document:document-property-delete', args=[item['pk']])
        return data

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['key_search'] = self.request.GET.get('key_search')
        return ctx


class DocumentPropertyDeleteView(apps.common.mixins.CustomDeleteView):
    model = DocumentProperty
    document = None

    def get_success_url(self):
        return self.request.POST.get('next') or reverse('document:document-detail',
                                                        args=[self.document.pk])

    def has_permission(self):
        self.document = self.get_object().document
        return self.request.user.can_view_document(self.document)


class DocumentRelationListView(apps.common.mixins.JqPaginatedListView):
    model = DocumentRelation
    json_fields = ['relation_type',
                   'document_a__pk',
                   'document_a__project__name',
                   'document_a__name',
                   'document_a__document_type__title', 'document_a__description',
                   'document_b__pk',
                   'document_b__project__name',
                   'document_b__name',
                   'document_b__document_type__title', 'document_b__description']
    limit_reviewers_qs_by_field = ['document_a', 'document_b']
    template_name = 'document/document_relation_list.html'

    def get_json_data(self, **kwargs):
        data = super().get_json_data()
        for item in data['data']:
            item['url_a'] = self.full_reverse('document:document-detail', args=[item['document_a__pk']])
            item['url_b'] = self.full_reverse('document:document-detail', args=[item['document_b__pk']])
        return data

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(
            Q(document_a__project_id__in=self.request.user.userprojectssavedfilter.projects.all()) |
            Q(document_b__project_id__in=self.request.user.userprojectssavedfilter.projects.all()))
        qs = qs.select_related('document_a', 'document_b')
        return qs


class DocumentDetailView(apps.common.mixins.PermissionRequiredMixin, DetailView):
    model = Document
    raise_exception = True

    def has_permission(self):
        return self.request.user.can_view_document(self.get_object())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        document = self.object

        # Fetch related lists
        party_usage_list = PartyUsage.objects \
            .filter(text_unit__document=document) \
            .values("party__name") \
            .annotate(count=Count("id")).order_by("-count")
        party_list = party_usage_list.values_list('party__name', flat=True)

        task_queue_list = document.taskqueue_set.all()
        extra_task_queue_list = TaskQueue.objects.exclude(
            id__in=task_queue_list.values_list('pk', flat=True))

        log_records = self.get_log_records()

        ctx.update({"document": document,
                    "party_list": list(party_list),
                    "extra_task_queue_list": extra_task_queue_list,
                    'log_records': log_records,
                    "highlight": self.request.GET.get("highlight", "")})

        rel_path = self.object.description or self.object.source_path or ''
        rel_url = os.path.join('/media',
                               settings.FILEBROWSER_DOCUMENTS_DIRECTORY.lstrip('/'),
                               rel_path.lstrip('/'))
        ctx['document_path'] = 'https://{host}{rel_url}'.format(
            host=Site.objects.get_current().domain, rel_url=rel_url)

        return ctx

    def get_log_records(self):
        document_id = self.object.pk
        query = {'bool': {
            'must': [
                {'term': {Document.LOG_FIELD_DOC_ID: {'value': f'{document_id}'}}},
            ]
        }}
        records = []  # type: List[Tuple[str, str, str, str, datetime.datetime]]
        for record in Task.get_task_log_from_elasticsearch_by_query(query):
            color = 'green'
            if record.log_level == 'WARN':
                color = 'yellow'
            elif record.log_level == 'ERROR':
                color = 'red'
            msg_type = record.log_level or 'INFO'
            records.append((record.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                            msg_type, record.message, color, record.timestamp,))
        records.sort(key=lambda r: r[-1], reverse=True)
        return records


class DocumentSourceView(DocumentDetailView):
    template_name = "document/document_source.html"

    def get_context_data(self, **kwargs):
        # TODO: detect protocol, don't hardcode
        # rel_url = os.path.join('/media',
        #                        settings.FILEBROWSER_DOCUMENTS_DIRECTORY.lstrip('/'),
        #                        self.object.description.lstrip('/'))

        rel_url = reverse('document:show-document', args=[self.object.pk])
        attachment = dict(
            name=self.object.name,
            path='https://{host}{rel_url}'.format(
                host=Site.objects.get_current().domain, rel_url=rel_url),
            extension=os.path.splitext(self.object.description)[1][1:].lower()
        )
        ctx = {'attachment': attachment}
        return ctx


def show_document(request, pk):
    """
    Show documents via django's view, not via media files
    to avoid nginx base authentication
    """
    document = Document.objects.get(pk=pk)
    file_name = document.name
    with file_storage.get_document_as_local_fn(document.source_path) as (full_name, _):
        mimetype = python_magic.from_file(full_name)
        response = FileResponse(open(full_name, 'rb'), content_type=mimetype)
        response['Content-Disposition'] = 'inline; filename="{}"'.format(file_name)
        return response


class DocumentNoteListView(apps.common.mixins.JqPaginatedListView):
    model = DocumentNote
    json_fields = ['note', 'timestamp', 'document__pk',
                   'document__project__name',
                   'document__name', 'document__document_type__title',
                   'document__description']
    limit_reviewers_qs_by_field = 'document'
    ordering = ['-timestamp']
    template_name = 'document/document_note_list.html'

    def get_json_data(self, **kwargs):
        data = super().get_json_data(keep_tags=True)
        history = list(
            DocumentNote.history
                .filter(document_id__in=list(self.get_queryset()
                                             .values_list('document__pk', flat=True)))
                .values('id', 'document_id', 'history_date', 'history_user__username', 'note'))

        for item in data['data']:
            item['url'] = self.full_reverse('document:document-detail', args=[item['document__pk']])
            item['delete_url'] = self.full_reverse('document:document-note-delete', args=[item['pk']])
            item_history = [i for i in history if i['id'] == item['pk']]
            if item_history:
                item['history'] = item_history
                item['user'] = sorted(item_history,
                                      key=lambda i: i['history_date'])[-1]['history_user__username']
        return data

    def get_queryset(self):
        qs = super().get_queryset()

        qs = qs.filter(document__project_id__in=self.request.user.userprojectssavedfilter.projects.all())

        if "document_pk" in self.request.GET:
            qs = qs.filter(document__pk=self.request.GET['document_pk'])
        return qs


class DocumentEnhancedView(DocumentDetailView):
    template_name = "document/document_enhanced_view.html"

    def get_context_data(self, **kwargs):
        document = self.object
        paragraph_list = document.textunit_set \
            .filter(unit_type="paragraph") \
            .order_by("id") \
            .prefetch_related(
            Prefetch(
                'termusage_set',
                queryset=TermUsage.objects.order_by('term__term').select_related('term'),
                to_attr='ltu'))
        ctx = {"document": document,
               "party_list": list(PartyUsage.objects.filter(
                   text_unit__document=document).values_list('party__name', flat=True)),
               "highlight": self.request.GET.get("highlight", ""),
               "paragraph_list": paragraph_list}
        return ctx


class TextUnitDetailView(apps.common.mixins.PermissionRequiredMixin, DetailView):
    """
    Used DetailView instead of CustomDetailView to overwrite
    admin permissions
    """
    model = TextUnit
    template_name = "document/text_unit_detail.html"
    raise_exception = True

    def has_permission(self):
        return self.request.user.can_view_document(self.get_object().document)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        text_unit = self.object
        document = text_unit.document

        ctx.update({"document": document,
                    "highlight": self.request.GET.get("highlight", ""),
                    "text_unit": text_unit})
        return ctx


class TextUnitListView(apps.common.mixins.JqPaginatedListView):
    model = TextUnit
    json_fields = ['unit_type', 'language',
                   'textunittext__text',
                   'text_hash',
                   'document__pk',
                   'document__project__name',
                   'document__name',
                   'document__document_type__title', 'document__description']
    limit_reviewers_qs_by_field = 'document'
    es = Elasticsearch(hosts=settings.ELASTICSEARCH_CONFIG['hosts'])
    template_name = 'document/text_unit_list.html'

    def get_queryset(self):
        qs = super().get_queryset().order_by('document_id', 'unit_type')

        if not "document_pk" in self.request.GET:
            qs = qs.filter(document__project_id__in=self.request.user.userprojectssavedfilter.projects.all())

        if "elastic_search" in self.request.GET:
            elastic_search = self.request.GET.get("elastic_search")
            es_query = {
                'query': {
                    'bool': {
                        'must': [
                            {'match': {'unit_type': 'paragraph'}},
                            {'match': {'text': elastic_search}},
                        ]
                    }
                }
            }
            es_res = self.es.search(size=1000, index=settings.ELASTICSEARCH_CONFIG['index'],
                                    body=es_query)
            # See UpdateElasticsearchIndex in tasks.py for the set of indexed fields
            pks = [hit['_source']['pk'] for hit in es_res['hits']['hits']]
            qs = TextUnit.objects.filter(pk__in=pks)
        elif "text_search" in self.request.GET:
            text_search = self.request.GET.get("text_search")
            qs = qs.filter(textunittext__text__icontains=text_search).order_by('id')
        if "document_pk" in self.request.GET:
            # Document Detail view, Party summary view
            qs = qs.filter(document__pk=self.request.GET['document_pk']).order_by('pk')
        if "party_pk" in self.request.GET:
            qs = qs.filter(partyusage__party__pk=self.request.GET['party_pk'])
        if "language" in self.request.GET:
            qs = qs.filter(language=self.request.GET['language'])
        if "text_unit_hash" in self.request.GET:
            # Text Unit Detail identical text units tab
            qs = qs.filter(text_hash=self.request.GET['text_unit_hash']) \
                .exclude(pk=self.request.GET['text_unit_pk'])
        if "cluster_id" in self.request.GET:
            qs = TextUnitCluster.objects.get(pk=self.request.GET['cluster_id']).text_units.all()

        # else:
        #     qs = qs.filter(unit_type='paragraph')
        return qs

    def get_json_data(self, **kwargs):
        data = super().get_json_data()
        for item in data['data']:
            item['url'] = self.full_reverse('document:document-detail', args=[item['document__pk']])
            item['detail_url'] = self.full_reverse('document:text-unit-detail', args=[item['pk']])
        return data

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['elastic_search'] = self.request.GET.get("elastic_search", "")
        ctx['text_search'] = self.request.GET.get("text_search", "")
        ctx['is_text_unit_list_page'] = True
        return ctx


class TextUnitByLangListView(apps.common.mixins.JqPaginatedListView):
    model = TextUnit
    template_name = 'document/text_unit_lang_list.html'
    limit_reviewers_qs_by_field = None

    def get_queryset(self):
        qs = super().get_queryset().order_by('document_id', 'unit_type')
        qs = qs.filter(document__project_id__in=self.request.user.userprojectssavedfilter.projects.all())
        return qs

    def get_json_data(self, **kwargs):
        qs = super().get_queryset()
        qs = qs.filter(unit_type='paragraph')
        data = list(qs.values('language').order_by().annotate(count=Count('pk')).order_by('-count'))
        for item in data:
            item['url'] = self.full_reverse('document:text-unit-list') + '?language=' + item['language']
        return {'data': data, 'total_records': len(data)}


class TextUnitPropertyListView(apps.common.mixins.JqPaginatedListView):
    model = TextUnitProperty
    limit_reviewers_qs_by_field = 'text_unit__document'
    json_fields = ['key', 'value',
                   'text_unit__document__pk',
                   'text_unit__document__project__name',
                   'text_unit__document__name',
                   'text_unit__document__document_type__title',
                   'text_unit__unit_type', 'text_unit__language',
                   'text_unit__pk']
    template_name = 'document/text_unit_property_list.html'

    def get_queryset(self):
        qs = super().get_queryset() \
            .select_related('text_unit__document__document_type') \
            .order_by('text_unit_id', 'key', 'value')

        qs = qs.filter(text_unit__document__project_id__in=self.request.user.userprojectssavedfilter.projects.all())

        if "text_unit_pk" in self.request.GET:
            qs = qs.filter(text_unit__pk=self.request.GET['text_unit_pk'])

        key_search = self.request.GET.get('key_search')
        if key_search:
            qs = qs.filter(key__icontains=key_search)
        return qs

    def get_json_data(self, **kwargs):
        data = super().get_json_data()
        for item in data['data']:
            item['url'] = self.full_reverse('document:document-detail',
                                            args=[item['text_unit__document__pk']])
            item['text_unit_url'] = self.full_reverse('document:text-unit-detail',
                                                      args=[item['text_unit__pk']])
            item['delete_url'] = self.full_reverse('document:text-unit-property-delete', args=[item['pk']])
        return data

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['key_search'] = self.request.GET.get('key_search')
        return ctx


class TextUnitPropertyDeleteView(apps.common.mixins.CustomDeleteView):
    model = TextUnitProperty

    def get_success_url(self):
        return self.request.POST.get('next') or reverse('document:tex-unit-detail',
                                                        args=[self.text_unit.pk])

    def has_permission(self):
        document = self.get_object().text_unit.document
        return self.request.user.can_view_document(document)


class TextUnitNoteListView(apps.common.mixins.JqPaginatedListView):
    model = TextUnitNote
    json_fields = ['note', 'timestamp', 'text_unit__document__pk',
                   'text_unit__document__project__name',
                   'text_unit__document__name', 'text_unit__document__document_type__title',
                   'text_unit__document__description', 'text_unit__pk',
                   'text_unit__unit_type', 'text_unit__language']
    limit_reviewers_qs_by_field = 'text_unit__document'
    template_name = 'document/text_unit_note_list.html'

    def get_json_data(self, **kwargs):
        data = super().get_json_data(keep_tags=True)
        history = list(
            TextUnitNote.history
                .filter(text_unit__document_id__in=list(
                self.get_queryset().values_list('text_unit__document__pk', flat=True)))
                .values('id', 'text_unit_id', 'history_date', 'history_user__username', 'note'))

        for item in data['data']:
            item['url'] = self.full_reverse('document:document-detail',
                                            args=[item['text_unit__document__pk']])
            item['detail_url'] = self.full_reverse('document:text-unit-detail', args=[item['text_unit__pk']])
            item['delete_url'] = self.full_reverse('document:text-unit-note-delete', args=[item['pk']])
            item_history = [i for i in history if i['id'] == item['pk']]
            if item_history:
                item['history'] = item_history
                item['user'] = sorted(item_history,
                                      key=lambda i: i['history_date'])[-1]['history_user__username']
        return data

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(text_unit__document__project_id__in=self.request.user.userprojectssavedfilter.projects.all())

        if "text_unit_pk" in self.request.GET:
            qs = qs.filter(text_unit__pk=self.request.GET['text_unit_pk'])
        return qs


class TextUnitNoteDeleteView(apps.common.mixins.CustomDeleteView):
    model = TextUnitNote

    def get_success_url(self):
        return reverse('document:text-unit-detail', args=[self.object.text_unit.pk])

    def has_permission(self):
        document = self.get_object().text_unit.document
        return self.request.user.can_view_document(document)


class DocumentNoteDeleteView(apps.common.mixins.CustomDeleteView):
    model = DocumentNote

    def get_success_url(self):
        return self.request.POST.get('next') or reverse('document:document-detail',
                                                        args=[self.object.document.pk])

    def has_permission(self):
        document = self.get_object().document
        return self.request.user.can_view_document(document)


class DocumentTagListView(apps.common.mixins.JqPaginatedListView):
    model = DocumentTag
    json_fields = ['tag', 'timestamp', 'user__username', 'document__pk',
                   'document__project__name',
                   'document__name', 'document__document_type__title',
                   'document__description']
    limit_reviewers_qs_by_field = 'document'
    template_name = 'document/document_tag_list.html'

    def get_json_data(self, **kwargs):
        data = super().get_json_data()
        for item in data['data']:
            item['url'] = self.full_reverse('document:document-detail',
                                            args=[item['document__pk']])
            item['delete_url'] = self.full_reverse('document:document-tag-delete', args=[item['pk']])
        return data

    def get_queryset(self):
        qs = super().get_queryset()

        qs = qs.filter(document__project_id__in=self.request.user.userprojectssavedfilter.projects.all())

        tag_search = self.request.GET.get('tag_search')
        if tag_search:
            qs = qs.filter(tag=tag_search)
        document_id = self.request.GET.get('document_id')
        if document_id:
            qs = qs.filter(document__id=document_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["tag_search"] = self.request.GET.get('tag_search')
        return ctx


class DocumentTagDeleteView(apps.common.mixins.CustomDeleteView):
    model = DocumentTag

    def get_success_url(self):
        return self.request.POST.get('next') or reverse('document:document-tag-list')

    def has_permission(self):
        document = self.get_object().document
        return self.request.user.can_view_document(document)


class TextUnitTagListView(apps.common.mixins.JqPaginatedListView):
    model = TextUnitTag
    json_fields = ['tag', 'timestamp', 'user__username', 'text_unit__document__pk',
                   'text_unit__document__project__name',
                   'text_unit__document__name', 'text_unit__document__document_type__title',
                   'text_unit__document__description', 'text_unit__pk',
                   'text_unit__unit_type', 'text_unit__language']
    limit_reviewers_qs_by_field = 'text_unit__document'
    template_name = 'document/text_unit_tag_list.html'

    def get_json_data(self, **kwargs):
        data = super().get_json_data()
        for item in data['data']:
            item['url'] = self.full_reverse('document:document-detail',
                                            args=[item['text_unit__document__pk']])
            item['detail_url'] = self.full_reverse('document:text-unit-detail', args=[item['text_unit__pk']])
            item['delete_url'] = self.full_reverse('document:text-unit-tag-delete', args=[item['pk']])
        return data

    def get_queryset(self):
        qs = super().get_queryset()

        qs = qs.filter(text_unit__document__project_id__in=self.request.user.userprojectssavedfilter.projects.all())

        tag_search = self.request.GET.get('tag_search')
        if tag_search:
            qs = qs.filter(tag=tag_search)
        text_unit_id = self.request.GET.get('text_unit_id')
        if text_unit_id:
            qs = qs.filter(text_unit__id=text_unit_id)
        qs = qs.select_related('text_unit', 'text_unit__document')
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["tag_search"] = self.request.GET.get('tag_search')
        return ctx


class TextUnitTagDeleteView(apps.common.mixins.CustomDeleteView):
    model = TextUnitTag

    def get_success_url(self):
        return self.request.POST.get('next') or reverse('document:text-unit-tag-list')

    def has_permission(self):
        document = self.get_object().text_unit.document
        return self.request.user.can_view_document(document)


class TypeaheadDocumentDescription(apps.common.mixins.TypeaheadView):
    model = Document
    search_field = 'description'
    limit_reviewers_qs_by_field = ''


class TypeaheadDocumentName(TypeaheadDocumentDescription):
    search_field = 'name'


class TypeaheadTextUnitTag(apps.common.mixins.TypeaheadView):
    model = TextUnitTag
    search_field = 'tag'
    limit_reviewers_qs_by_field = 'text_unit__document'


class TypeaheadDocumentPropertyKey(apps.common.mixins.TypeaheadView):
    model = DocumentProperty
    search_field = 'key'
    limit_reviewers_qs_by_field = 'document'


class SubmitNoteView(apps.common.mixins.SubmitView):
    notes_map = dict(
        document=dict(
            owner_model=Document,
            note_model=DocumentNote,
            owner_field='document'
        ),
        text_unit=dict(
            owner_model=TextUnit,
            note_model=TextUnitNote,
            owner_field='text_unit'
        )
    )
    success_message = 'Note was successfully saved'

    @staticmethod
    def get_owner(request, owner_model=TextUnit):
        try:
            owner = owner_model.objects.get(id=request.POST["owner_id"])
            document = owner if owner_model == Document else owner.document
            if not request.user.can_view_document(document):
                # TODO: specify error message
                return None
        except owner_model.DoesNotExist:
            return None
        return owner

    def process(self, request):
        note_prop = self.notes_map[request.POST.get("owner_name", "text_unit")]
        owner = self.get_owner(request, note_prop['owner_model'])
        note_model = note_prop['note_model']
        if owner is None:
            return self.failure()
        if request.POST.get("note_id"):
            try:
                obj = note_model.objects.get(pk=request.POST["note_id"])
            except note_model.DoesNotExist:
                return self.failure()
        else:
            obj = note_model()
            setattr(obj, note_prop['owner_field'], owner)
        obj.note = request.POST["note"]
        obj.save()
        return self.success()


class SubmitDocumentTagView(apps.common.mixins.SubmitView):
    owner = None
    owner_class = Document
    tag_class = DocumentTag
    owner_field = 'document'

    def dispatch(self, request, *args, **kwargs):
        self.owner = self.get_owner(request)
        return super().dispatch(request, *args, **kwargs)

    def get_success_message(self):
        return "Successfully added tag /%s/ for %s" % (
            self.request.POST["tag"],
            str(self.owner))

    @staticmethod
    def allowed(user, owner):
        return user.can_view_document(owner)

    def get_owner(self, request):
        try:
            owner = self.owner_class.objects.get(id=request.POST["owner_id"])
            if not self.allowed(request.user, owner):
                self.error_message = 'Not Allowed'
                return None
        except self.owner_class.DoesNotExist:
            self.error_message = 'Not Found'
            return None
        return owner

    def process(self, request):
        if not self.owner:
            return self.failure()
        defaults = {
            self.owner_field: self.owner,
            'tag': request.POST['tag'],
            'user': request.user,
            'timestamp': datetime.datetime.now()
        }
        if self.request.POST.get('tag_pk'):
            obj, created = self.tag_class.objects.update_or_create(
                pk=self.request.POST['tag_pk'],
                defaults=defaults)
        else:
            obj = self.tag_class.objects.create(**defaults)
            created = True
        action = 'created' if created else 'updated'
        self.success_message = '%s Tag %s was successfully %s' \
                               % (cap_words(self.owner_class._meta.verbose_name), str(obj), action)
        return self.success()


class SubmitClusterDocumentsTagView(apps.common.mixins.SubmitView):
    owner = None
    owner_class = DocumentCluster
    tag_class = DocumentTag
    owner_field = 'document'

    def dispatch(self, request, *args, **kwargs):
        self.owner = self.get_owner(request)
        return super().dispatch(request, *args, **kwargs)

    def get_success_message(self):
        return "Successfully added tag /%s/ for cluster /%s/ documents" % (
            self.request.POST["tag"],
            str(self.owner))

    @staticmethod
    def allowed(user, owner):
        # return user.can_view_document(owner)
        return True

    def get_owner(self, request):
        try:
            owner = self.owner_class.objects.get(id=request.POST["owner_id"])
            if not self.allowed(request.user, owner):
                self.error_message = 'Not Allowed'
                return None
        except self.owner_class.DoesNotExist:
            self.error_message = 'Not Found'
            return None
        return owner

    def process(self, request):
        if not self.owner:
            return self.failure()
        timestamp = datetime.datetime.now()
        tags = [self.tag_class(**{
            self.owner_field: owner,
            'tag': request.POST['tag'],
            'user': request.user,
            'timestamp': timestamp}) for owner in self.owner.documents.all()]
        self.tag_class.objects.bulk_create(tags)
        return self.success()


class SubmitClusterDocumentsPropertyView(SubmitClusterDocumentsTagView):
    owner_class = DocumentCluster
    property_class = DocumentProperty

    def get_success_message(self):
        return "Successfully added property %s:%s for cluster %s documents" % (
            self.request.POST["key"],
            self.request.POST["value"],
            str(self.owner))

    def process(self, request):
        if not self.owner:
            return self.failure()
        properties = [self.property_class(**{
            self.owner_field: owner,
            'key': request.POST['key'],
            'value': request.POST['value']}) for owner in self.owner.documents.all()]
        # use save instead of bulk_create to call save method on model
        for prop in properties:
            prop.save()
        return self.success()


class SubmitClusterDocumentsLanguageView(SubmitClusterDocumentsTagView):
    owner_class = DocumentCluster

    def get_success_message(self):
        return "Successfully changed language to %s for cluster %s documents" % (
            self.request.POST["language"],
            str(self.owner))

    def process(self, request):
        if not self.owner:
            return self.failure()
        text_units = TextUnit.objects.filter(document__documentcluster=self.owner)
        text_units.update(language=self.request.POST["language"])
        return self.success()


class SubmitTextUnitTagView(SubmitDocumentTagView):
    owner_class = TextUnit
    tag_class = TextUnitTag
    owner_field = 'text_unit'

    @staticmethod
    def allowed(user, owner):
        return user.can_view_document(owner.document)


class SubmitDocumentPropertyView(SubmitDocumentTagView):
    property_class = DocumentProperty

    def get_success_message(self):
        return "Successfully added property for %s" % str(self.owner)

    def process(self, request):
        if not self.owner:
            return self.failure()
        defaults = {
            self.owner_field: self.owner,
            'key': request.POST['key'],
            'value': request.POST['value']
        }
        if self.request.POST.get('property_pk'):
            _, created = self.property_class.objects.update_or_create(
                pk=self.request.POST['property_pk'],
                defaults=defaults)
        else:
            self.property_class.objects.create(**defaults)
            created = True
        action = 'created' if created else 'updated'
        self.success_message = '%s Property was successfully %s' \
                               % (cap_words(self.owner_class._meta.verbose_name), action)
        return self.success()


class SubmitTextUnitPropertyView(SubmitDocumentPropertyView):
    owner_class = TextUnit
    property_class = TextUnitProperty
    owner_field = 'text_unit'

    @staticmethod
    def allowed(user, owner):
        return user.can_view_document(owner.document)


def view_stats(request):
    """
    Display overall statistics.
    :param request:
    :return:
    """
    admin_task_df = pd.DataFrame(TaskListView(request=request).get_json_data()['data'])
    admin_task_total_count = admin_task_df.shape[0]
    admin_task_by_status_count = dict(admin_task_df.groupby(['status']).size()) \
        if not admin_task_df.empty else 0

    project_df = pd.DataFrame(ProjectListView(request=request).get_json_data()['data'])
    if project_df.empty:
        project_total_count = project_completed_count = project_completed_weight = \
            project_progress_avg = project_documents_total_count = \
            project_documents_unique_count = 0
    else:
        project_df['completed'] = project_df['completed'].astype(int)
        project_total_count = project_df.shape[0]
        project_df_sum = project_df.sum()
        project_completed_count = project_df_sum.completed
        project_completed_weight = round(project_completed_count / project_total_count * 100, 1)
        project_progress_avg = round(project_df.mean().progress, 1)
        project_documents_total_count = project_df_sum.total_documents_count
        project_documents_unique_count = Document.objects.filter().distinct('name', 'file_size').count()

    task_queue_df = pd.DataFrame(TaskQueueListView(request=request).get_json_data()['data'])
    if task_queue_df.empty:
        task_queue_total_count = task_queue_completed_count = task_queue_completed_weight = \
            task_queue_progress_avg = task_queue_documents_total_count = \
            task_queue_documents_unique_count = task_queue_reviewers_unique_count = 0
    else:
        task_queue_df['completed'] = task_queue_df['completed'].astype(int)
        task_queue_total_count = task_queue_df.shape[0]
        task_queue_df_sum = task_queue_df.sum()
        task_queue_completed_count = task_queue_df_sum.completed
        task_queue_completed_weight = round(
            task_queue_completed_count / task_queue_total_count * 100, 1)
        task_queue_progress_avg = round(task_queue_df.mean().progress, 1)
        task_queue_documents_total_count = task_queue_df_sum.total_documents_count
        task_queue_documents_unique_count = Document.objects.filter(taskqueue__isnull=False) \
            .distinct().count()
        task_queue_reviewers_unique_count = User.objects.filter(taskqueue__isnull=False) \
            .distinct().count()

    # set counts depending on user role
    documents = Document.objects
    document_properties = DocumentProperty.objects
    document_tags = DocumentTag.objects
    document_notes = DocumentNote.objects
    document_relations = DocumentRelation.objects
    document_clusters = DocumentCluster.objects
    text_units = TextUnit.objects
    tu_tags = TextUnitTag.objects
    tu_properties = TextUnitProperty.objects
    tu_classifications = TextUnitClassification.objects
    tu_classification_suggestions = TextUnitClassifierSuggestion.objects
    tuc_suggestion_types = TextUnitClassifierSuggestion.objects.distinct('class_name')
    tu_notes = TextUnitNote.objects
    tu_clusters = TextUnitCluster.objects

    terms = Term.objects
    term_usages = TermUsage.objects

    amount_usages = AmountUsage.objects
    citation_usages = CitationUsage.objects
    copyright_usages = CopyrightUsage.objects
    court_usages = CourtUsage.objects
    currency_usages = CurrencyUsage.objects
    date_duration_usages = DateDurationUsage.objects
    date_usages = DateUsage.objects
    definition_usages = DefinitionUsage.objects
    distance_usages = DistanceUsage.objects
    geo_entities = GeoEntity.objects
    geo_entity_usages = GeoEntityUsage.objects
    geo_aliases = GeoAlias.objects
    geo_alias_usages = GeoAliasUsage.objects
    geo_relations = GeoRelation.objects
    parties = Party.objects
    party_usages = PartyUsage.objects
    percent_usages = PercentUsage.objects
    ratio_usages = RatioUsage.objects
    regulation_usages = RegulationUsage.objects
    trademark_usages = TrademarkUsage.objects
    url_usages = UrlUsage.objects

    if request.user.is_reviewer:
        document_filter_opts = dict(document__taskqueue__reviewers=request.user)
        tu_filter_opts = dict(text_unit__document__taskqueue__reviewers=request.user)

        documents = documents.filter(taskqueue__reviewers=request.user).distinct()
        document_properties = document_properties.filter(**document_filter_opts).distinct()
        document_tags = document_tags.filter(**document_filter_opts).distinct()
        document_notes = document_notes.filter(**document_filter_opts).distinct()
        document_relations = document_relations.filter(
            document_a__taskqueue__reviewers=request.user,
            document_b__taskqueue__reviewers=request.user).distinct()
        document_clusters = document_clusters.filter(
            documents__taskqueue__reviewers=request.user).distinct()
        text_units = text_units.filter(**document_filter_opts).distinct()
        tu_tags = tu_tags.filter(**tu_filter_opts).distinct()
        tu_properties = tu_properties.filter(**tu_filter_opts).distinct()
        tu_classifications = tu_classifications.filter(**tu_filter_opts).distinct()
        tu_classification_suggestions = tu_classification_suggestions.filter(
            **tu_filter_opts).distinct()
        tuc_suggestion_types = tuc_suggestion_types.filter(**tu_filter_opts).distinct('class_name')
        tu_notes = tu_notes.filter(**tu_filter_opts).distinct()
        tu_clusters = tu_clusters.filter(
            text_units__document__taskqueue__reviewers=request.user).distinct()
        terms = terms.filter(
            termusage__text_unit__document__taskqueue__reviewers=request.user).distinct()
        term_usages = term_usages.filter(**tu_filter_opts).distinct()

        amount_usages = amount_usages.filter(**tu_filter_opts).distinct()
        citation_usages = citation_usages.filter(**tu_filter_opts).distinct()
        copyright_usages = copyright_usages.filter(**tu_filter_opts).distinct()
        court_usages = court_usages.filter(**tu_filter_opts).distinct()
        currency_usages = currency_usages.filter(**tu_filter_opts).distinct()
        date_duration_usages = date_duration_usages.filter(**tu_filter_opts).distinct()
        date_usages = date_usages.filter(**tu_filter_opts).distinct()
        definition_usages = definition_usages.filter(**tu_filter_opts).distinct()
        distance_usages = distance_usages.filter(**tu_filter_opts).distinct()

        geo_aliases = geo_aliases.filter(
            geoaliasusage__text_unit__document__taskqueue__reviewers=request.user).distinct()
        geo_alias_usages = geo_alias_usages.filter(**tu_filter_opts).distinct()
        geo_entities = geo_entities.filter(
            geoentityusage__text_unit__document__taskqueue__reviewers=request.user).distinct()
        geo_entity_usages = geo_entity_usages.filter(**tu_filter_opts).distinct()
        geo_relations = geo_relations.filter(
            entity_a__geoentityusage__text_unit__document__taskqueue__reviewers=request.user,
            entity_b__geoentityusage__text_unit__document__taskqueue__reviewers=request.user) \
            .distinct()

        parties = parties.filter(
            partyusage__text_unit__document__taskqueue__reviewers=request.user).distinct()
        party_usages = party_usages.filter(**tu_filter_opts).distinct()
        percent_usages = percent_usages.filter(**tu_filter_opts).distinct()
        ratio_usages = ratio_usages.filter(**tu_filter_opts).distinct()
        regulation_usages = regulation_usages.filter(**tu_filter_opts).distinct()
        trademark_usages = trademark_usages.filter(**tu_filter_opts).distinct()
        url_usages = url_usages.filter(**tu_filter_opts).distinct()

    context = {
        "document_count": documents.count(),
        "document_property_count": document_properties.count(),
        "document_tag_count": document_tags.count(),
        "document_note_count": document_notes.count(),
        "document_relation_count": document_relations.count(),
        "document_cluster_count": document_clusters.count(),
        "text_unit_count": text_units.count(),
        "text_unit_tag_count": tu_tags.count(),
        "text_unit_property_count": tu_properties.count(),
        "text_unit_classification_count": tu_classifications.count(),
        "text_unit_classification_suggestion_count": tu_classification_suggestions.count(),
        "text_unit_classification_suggestion_type_count": tuc_suggestion_types.count(),
        "text_unit_note_count": tu_notes.count(),
        "text_unit_cluster_count": tu_clusters.count(),
        "amount_usage_count": amount_usages.count(),
        "citation_usage_count": citation_usages.count(),
        "copyright_usage_count": copyright_usages.count(),
        "court_count": Court.objects.count(),
        "court_usage_count": court_usages.count(),
        "currency_usage_count": currency_usages.count(),
        "date_duration_usage_count": date_duration_usages.count(),
        "date_usage_count": date_usages.count(),
        "definition_usage_count": definition_usages.count(),
        "distance_usage_count": distance_usages.count(),

        "geo_alias_count": geo_aliases.count(),
        "geo_alias_usage_count": geo_alias_usages.count(),
        "geo_entity_count": geo_entities.count(),
        "geo_entity_usage_count": geo_entity_usages.count(),
        "geo_relation_count": geo_relations.count(),
        "party_count": parties.count(),
        "party_usage_count": party_usages.count(),
        "percent_usage_count": percent_usages.count(),
        "ratio_usage_count": ratio_usages.count(),
        "regulation_usage_count": regulation_usages.count(),
        "trademark_usage_count": trademark_usages.count(),
        "url_usage_count": url_usages.count(),
        "term_count": terms.count(),
        "term_usage_count": term_usages.count(),
        "project_total_count": project_total_count,
        "project_completed_count": project_completed_count,
        "project_completed_weight": project_completed_weight,
        "project_progress_avg": project_progress_avg,
        "project_documents_total_count": project_documents_total_count,
        "project_documents_unique_count": project_documents_unique_count,
        "task_queue_total_count": task_queue_total_count,
        "task_queue_completed_count": task_queue_completed_count,
        "task_queue_completed_weight": task_queue_completed_weight,
        "task_queue_progress_avg": task_queue_progress_avg,
        "task_queue_documents_total_count": task_queue_documents_total_count,
        "task_queue_documents_unique_count": task_queue_documents_unique_count,
        "task_queue_reviewers_unique_count": task_queue_reviewers_unique_count,
        "admin_task_total_count": admin_task_total_count,
        "admin_task_by_status_count": admin_task_by_status_count,
    }

    return render(request, "document/stats.html", context)


class DetectFieldValuesTaskView(BaseAjaxTaskView):
    task_name = 'Detect Field Values'
    form_class = DetectFieldValuesForm
    html_form_class = 'popup-form build-field-detector-dataset-form'


class TrainDocumentFieldDetectorModelTaskView(BaseAjaxTaskView):
    task_name = 'Train Document Field Detector Model'
    form_class = TrainDocumentFieldDetectorModelForm
    html_form_class = 'popup-form train-field-detector-model-form'


class FindBrokenDocumentFieldValuesTaskView(BaseAjaxTaskView):
    task_name = FindBrokenDocumentFieldValues.name
    form_class = FindBrokenDocumentFieldValuesForm
    html_form_class = 'popup-form find-broken-document-field-values-form'


class FixDocumentFieldCodesTaskView(BaseAjaxTaskView):
    task_name = FixDocumentFieldCodes.name
    form_class = FixDocumentFieldCodesForm
    html_form_class = 'popup-form fix-document-field-codes-form'


class TrainAndTestTaskView(BaseAjaxTaskView):
    task_name = 'Train And Test'
    form_class = TrainAndTestForm
    html_form_class = 'popup-form train-and-test-form'


class LoadDocumentWithFieldsView(BaseAjaxTaskView):
    task_name = 'Load Document With Fields'
    form_class = LoadDocumentWithFieldsForm

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)
        data = None
        document_fields = None

        if form.is_valid():
            data = form.data
            document_fields = data.get('document_fields')
            source_data = data.get('source_data')
            document_name = data.get('document_name')
            if document_fields:
                if not document_name:
                    form.add_error('document_name', 'Document name should be specified if you specified the fields.')
                try:
                    document_fields = json.loads(document_fields)
                except:
                    form.add_error('document_fields', 'Incorrect JSON format')
            else:
                if not source_data:
                    form.add_error('source_data', 'Either document document fields or source path should be specified.')

        if not form.is_valid():
            return self.json_response(form.errors, status=400)

        document_name = data.get('document_name')

        call_task(
            task_name='LoadDocumentWithFields',
            module_name='apps.document.tasks',
            source_data=data.get('source_data'),
            project_id=data.get('project'),
            document_type_id=data.get('document_type'),
            document_name=document_name,
            document_fields=document_fields,
            run_detect_field_values=data.get('run_detect_field_values')
        )
        return self.json_response('The task is started. It can take a while.')


class ImportCSVFieldDetectionConfigView(BaseAjaxTaskView):
    task_name = ImportCSVFieldDetectionConfig.name
    form_class = ImportCSVFieldDetectionConfigForm
    html_form_class = 'popup-form import-csv-field-detection-config-form'


class ExportDocumentTypeView(LoadFixturesView):
    form_class = ExportDocumentTypeForm

    html_form_class = 'popup-form export-document-type-form'

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)
        if not form.is_valid():
            return self.json_response(form.errors, status=400)
        document_type = form.cleaned_data['document_type']
        json_data = get_app_config_dump([document_type.code])
        return download(json_data, '{0}_{1}'.format(document_type.code, str(datetime.date.today())))


class ImportDocumentTypeView(BaseAjaxTaskView):
    task_name = ImportDocumentType.name
    form_class = ImportDocumentTypeForm

    html_form_class = 'popup-form import-document-type-form'


class IdentifyContractsView(BaseAjaxTaskView):
    form_class = IdentifyContractsForm
    html_form_class = 'popup-form reindex'
    task_name = TASK_NAME_IDENTIFY_CONTRACTS

    def disallow_start(self):
        return False

    def start_task(self, data):
        document_type = data.get('document_type', {})
        document_type_code = document_type.code if document_type else None
        force = data.get('recheck_contract') or False
        proj = data.get('project') or None
        proj_id = proj.pk if proj else None  # type:Optional[int]
        call_task_func(identify_contracts, (document_type_code, force, proj_id),
                       data['user_id'])
