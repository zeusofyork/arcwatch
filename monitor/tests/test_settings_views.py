# monitor/tests/test_settings_views.py
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from monitor.models import Organization, GPUCluster, GPUNode, Invite


def _make_user_and_org(username='admin', role='owner'):
    """Helper: create a User + Organization + wire UserProfile."""
    user = User.objects.create_user(username=username, password='pw')
    org = Organization.objects.create(name='TestOrg', slug=f'testorg-{username}', owner=user)
    user.profile.organization = org
    user.profile.role = role
    user.profile.save()
    return user, org


class InviteModelTest(TestCase):
    def test_invite_created_with_expiry(self):
        user, org = _make_user_and_org('inviteadmin')
        invite = Invite.objects.create(
            organization=org,
            invited_by=user,
            email='new@example.com',
            role='viewer',
        )
        self.assertIsNotNone(invite.token)
        self.assertFalse(invite.is_expired)
        self.assertFalse(invite.is_accepted)
        import datetime as _dt
        from django.utils import timezone as _tz
        self.assertIsNotNone(invite.expires_at)
        expected_expiry = _tz.now() + _dt.timedelta(days=7)
        delta = abs((invite.expires_at - expected_expiry).total_seconds())
        self.assertLess(delta, 5, "expires_at should be approximately 7 days from now")

    def test_is_active_on_cluster_and_node(self):
        user, org = _make_user_and_org('clusteradmin')
        cluster = GPUCluster.objects_unscoped.create(organization=org, name='test-cluster')
        self.assertTrue(cluster.is_active)
        node = GPUNode.objects_unscoped.create(
            organization=org, cluster=cluster,
            hostname='node-1', gpu_count=1, gpu_type='H100',
        )
        self.assertTrue(node.is_active)


class AuthRedirectTest(TestCase):
    def test_dashboard_redirects_to_login_when_unauthenticated(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_settings_redirects_to_login_when_unauthenticated(self):
        response = self.client.get('/settings/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_login_page_renders(self):
        response = self.client.get('/accounts/login/')
        self.assertEqual(response.status_code, 200)


class DecoratorTest(TestCase):
    def setUp(self):
        self.admin, self.org = _make_user_and_org('dec_admin', role='owner')
        self.viewer = User.objects.create_user(username='dec_viewer', password='pw')
        self.viewer.profile.organization = self.org
        self.viewer.profile.role = 'viewer'
        self.viewer.profile.save()

    def test_require_admin_allows_admin(self):
        from monitor.decorators import require_admin
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage
        factory = RequestFactory()
        req = factory.post('/fake/')
        req.user = self.admin
        req.session = self.client.session
        req._messages = FallbackStorage(req)

        @require_admin
        def my_view(request):
            from django.http import HttpResponse
            return HttpResponse('ok')

        response = my_view(req)
        self.assertEqual(response.status_code, 200)

    def test_require_admin_rejects_viewer(self):
        from monitor.decorators import require_admin
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage
        factory = RequestFactory()
        req = factory.post('/fake/')
        req.user = self.viewer
        req.session = self.client.session
        req._messages = FallbackStorage(req)

        @require_admin
        def my_view(request):
            from django.http import HttpResponse
            return HttpResponse('ok')

        response = my_view(req)
        self.assertEqual(response.status_code, 403)


class SettingsNavTest(TestCase):
    def setUp(self):
        self.user, self.org = _make_user_and_org('nav_user', role='admin')
        self.client.login(username='nav_user', password='pw')

    def test_settings_redirect_to_api_keys(self):
        response = self.client.get('/settings/')
        self.assertRedirects(response, '/settings/api-keys/', fetch_redirect_response=False)

    def test_api_keys_page_returns_200(self):
        response = self.client.get('/settings/api-keys/')
        self.assertEqual(response.status_code, 200)

    def test_alert_rules_page_returns_200(self):
        response = self.client.get('/settings/alert-rules/')
        self.assertEqual(response.status_code, 200)

    def test_resources_page_returns_200(self):
        response = self.client.get('/settings/resources/')
        self.assertEqual(response.status_code, 200)

    def test_members_page_returns_200(self):
        response = self.client.get('/settings/members/')
        self.assertEqual(response.status_code, 200)


class APIKeysPageTest(TestCase):
    def setUp(self):
        self.admin, self.org = _make_user_and_org('api_admin', role='owner')
        self.viewer = User.objects.create_user(username='api_viewer', password='pw')
        self.viewer.profile.organization = self.org
        self.viewer.profile.role = 'viewer'
        self.viewer.profile.save()

    def test_create_api_key_returns_raw_key_in_context(self):
        self.client.login(username='api_admin', password='pw')
        response = self.client.post('/settings/api-keys/', {
            'name': 'Test Key',
            'scopes': ['ingest'],
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('new_raw_key', response.context)
        self.assertIsNotNone(response.context['new_raw_key'])

    def test_create_api_key_viewer_gets_403(self):
        self.client.login(username='api_viewer', password='pw')
        response = self.client.post('/settings/api-keys/', {
            'name': 'Test Key',
            'scopes': ['ingest'],
        })
        self.assertEqual(response.status_code, 403)

    def test_revoke_sets_active_false(self):
        from monitor.models import APIKey
        self.client.login(username='api_admin', password='pw')
        api_key, _ = APIKey.create_key(self.org, self.admin, 'ToRevoke', ['ingest'])
        response = self.client.post(f'/settings/api-keys/{api_key.id}/revoke/', follow=True)
        self.assertEqual(response.status_code, 200)
        api_key.refresh_from_db()
        self.assertFalse(api_key.active)

    def test_revoke_viewer_gets_403(self):
        from monitor.models import APIKey
        self.client.login(username='api_viewer', password='pw')
        api_key, _ = APIKey.create_key(self.org, self.admin, 'ToRevoke2', ['ingest'])
        response = self.client.post(f'/settings/api-keys/{api_key.id}/revoke/')
        self.assertEqual(response.status_code, 403)
