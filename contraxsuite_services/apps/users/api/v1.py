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

from django.conf.urls import url

# Third-party imports
import coreapi
import coreschema
from django.http import JsonResponse
from rest_framework import routers, viewsets, serializers, views, schemas
from django.core import serializers as core_serializers
from rest_framework.response import Response

# Project imports
import settings
from apps.common.api.permissions import ReviewerReadOnlyPermission
from apps.common.mixins import JqListAPIMixin, SimpleRelationSerializer
from apps.common.model_utils.improved_django_json_encoder import ImprovedDjangoJSONEncoder
from apps.users.models import User, Role

__author__ = "ContraxSuite, LLC; LexPredict, LLC"
__copyright__ = "Copyright 2015-2020, ContraxSuite, LLC"
__license__ = "https://github.com/LexPredict/lexpredict-contraxsuite/blob/1.7.0/LICENSE"
__version__ = "1.7.0"
__maintainer__ = "LexPredict, LLC"
__email__ = "support@contraxsuite.com"


# --------------------------------------------------------
# Role Views
# --------------------------------------------------------

class RoleSerializer(SimpleRelationSerializer):
    class Meta:
        model = Role
        fields = ['id', 'name', 'code', 'abbr', 'order',
                  'is_admin', 'is_top_manager', 'is_manager', 'is_reviewer']


class RoleViewSet(JqListAPIMixin, viewsets.ModelViewSet):
    """
    list: Role List
    create: Create Role
    retrieve: Retrieve Role
    update: Update Role
    partial_update: Partial Update Role
    """
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    http_method_names = ['get', 'post', 'put', 'patch']
    permission_classes = (ReviewerReadOnlyPermission,)


# --------------------------------------------------------
# User Views
# --------------------------------------------------------

class UserSerializer(SimpleRelationSerializer):
    full_name = serializers.SerializerMethodField()
    role_data = RoleSerializer(source='role', many=False, required=False)
    photo = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'last_name', 'first_name', 'full_name',
                  'email', 'is_superuser', 'is_staff', 'is_active',
                  'name', 'role', 'role_data', 'organization', 'photo']

    def get_photo(self, obj):
        return obj.photo.url if obj.photo else None

    def get_full_name(self, obj):
        return obj.get_full_name()


class UserViewSet(JqListAPIMixin, viewsets.ModelViewSet):
    """
    list: User List
    create: Create User
    retrieve: Retrieve User
    update: Update User
    partial_update: Partial Update User
    """
    queryset = User.objects.all().select_related('role')
    serializer_class = UserSerializer
    http_method_names = ['get', 'post', 'put', 'patch']
    permission_classes = (ReviewerReadOnlyPermission,)


class VerifyAuthTokenAPIView(views.APIView):

    authentication_classes = []
    permission_classes = []
    http_method_names = ['post']

    @property
    def coreapi_schema(self):
        fields = [
            coreapi.Field(
                "auth_token",
                required=True,
                location="form",
                schema=coreschema.String(max_length=40),
            )]
        return schemas.ManualSchema(fields=fields)

    def post(self, request, *args, **kwargs):
        auth_token = request.POST.get('auth_token') or request.data.get('auth_token') \
            or request.META.get('HTTP_AUTH_TOKEN')
        if not auth_token and request.COOKIES:
            auth_token = request.COOKIES.get('auth_token').replace('Token ', '')
        from apps.users.authentication import CookieAuthentication

        try:
            tok_usr, _tok = CookieAuthentication().authenticate_credentials(auth_token)
        except Exception as e:
            raise e

        if tok_usr:
            raw_data = core_serializers.serialize('python', [tok_usr])
            role_raw_data = core_serializers.serialize('python', [tok_usr.role])
            role_data = [d['fields'] for d in role_raw_data][0]
            usr_data = [d['fields'] for d in raw_data][0]
            del usr_data['password']
            del usr_data['user_permissions']
            usr_data['id'] = tok_usr.pk
            usr_data['role_data'] = role_data
            role_data['id'] = tok_usr.role.pk
            role_data['is_reviewer'] = tok_usr.role.is_reviewer
            resp_data = {
                'key': auth_token,
                'user_name': tok_usr.username,
                'user': usr_data,
                'release_version': settings.VERSION_NUMBER
            }
            return JsonResponse(resp_data, encoder=ImprovedDjangoJSONEncoder, safe=False)
        return Response()


router = routers.DefaultRouter()
router.register(r'users', UserViewSet, 'user')
router.register(r'roles', RoleViewSet, 'role')


urlpatterns = [
    url(r'verify-token/$', VerifyAuthTokenAPIView.as_view(), name='verify-token'),
]
