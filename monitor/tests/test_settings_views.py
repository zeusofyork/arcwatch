# monitor/tests/test_settings_views.py
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from unittest.mock import patch
from monitor.models import Organization, GPUCluster, GPUNode, Invite, AlertRule


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
    def test_landing_page_renders_when_unauthenticated(self):
        # Root now shows a public landing page instead of redirecting to login
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    def test_dashboard_redirects_to_login_when_unauthenticated(self):
        response = self.client.get('/dashboard/')
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


class AlertRulesPageTest(TestCase):
    def setUp(self):
        self.admin, self.org = _make_user_and_org('ar_admin', role='owner')
        self.viewer = User.objects.create_user(username='ar_viewer', password='pw')
        self.viewer.profile.organization = self.org
        self.viewer.profile.role = 'viewer'
        self.viewer.profile.save()
        self.rule = AlertRule.objects.create(
            organization=self.org,
            name='Test Rule',
            metric='gpu_utilization_low',
            threshold_value=20.0,
            is_enabled=True,
        )

    def test_create_alert_rule(self):
        self.client.login(username='ar_admin', password='pw')
        response = self.client.post('/settings/alert-rules/create/', {
            'name': 'New Rule',
            'metric': 'gpu_offline',
            'threshold_value': '0',
            'duration_seconds': '300',
            'slack_webhook_url': '',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AlertRule.objects.filter(name='New Rule', organization=self.org).exists())

    def test_create_alert_rule_viewer_gets_403(self):
        self.client.login(username='ar_viewer', password='pw')
        response = self.client.post('/settings/alert-rules/create/', {
            'name': 'X', 'metric': 'gpu_offline', 'threshold_value': '0',
            'duration_seconds': '300', 'slack_webhook_url': '',
        })
        self.assertEqual(response.status_code, 403)

    def test_toggle_alert_rule(self):
        self.client.login(username='ar_admin', password='pw')
        response = self.client.post(f'/settings/alert-rules/{self.rule.id}/toggle/')
        self.assertEqual(response.status_code, 200)
        self.rule.refresh_from_db()
        self.assertFalse(self.rule.is_enabled)

    def test_delete_alert_rule(self):
        self.client.login(username='ar_admin', password='pw')
        response = self.client.post(f'/settings/alert-rules/{self.rule.id}/delete/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AlertRule.objects.filter(pk=self.rule.id).exists())

    def test_cross_org_toggle_returns_404(self):
        """User from org B cannot toggle a rule belonging to org A."""
        other_user, other_org = _make_user_and_org('ar_other', role='owner')
        self.client.login(username='ar_other', password='pw')
        response = self.client.post(f'/settings/alert-rules/{self.rule.id}/toggle/')
        self.assertEqual(response.status_code, 404)

    def test_cross_org_delete_returns_404(self):
        """User from org B cannot delete a rule belonging to org A."""
        other_user, other_org = _make_user_and_org('ar_other2', role='owner')
        self.client.login(username='ar_other2', password='pw')
        response = self.client.post(f'/settings/alert-rules/{self.rule.id}/delete/')
        self.assertEqual(response.status_code, 404)


class ResourcesPageTest(TestCase):
    def setUp(self):
        self.admin, self.org = _make_user_and_org('res_admin', role='owner')
        self.viewer = User.objects.create_user(username='res_viewer', password='pw')
        self.viewer.profile.organization = self.org
        self.viewer.profile.role = 'viewer'
        self.viewer.profile.save()

    def test_create_cluster(self):
        self.client.login(username='res_admin', password='pw')
        response = self.client.post('/settings/resources/clusters/create/', {'name': 'prod-cluster'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(GPUCluster.objects_unscoped.filter(name='prod-cluster', organization=self.org).exists())

    def test_deactivate_cluster(self):
        self.client.login(username='res_admin', password='pw')
        cluster = GPUCluster.objects_unscoped.create(organization=self.org, name='to-deactivate')
        response = self.client.post(f'/settings/resources/clusters/{cluster.id}/deactivate/')
        self.assertEqual(response.status_code, 200)
        cluster.refresh_from_db()
        self.assertFalse(cluster.is_active)

    def test_deactivate_cluster_viewer_gets_403(self):
        self.client.login(username='res_viewer', password='pw')
        cluster = GPUCluster.objects_unscoped.create(organization=self.org, name='cluster-v')
        response = self.client.post(f'/settings/resources/clusters/{cluster.id}/deactivate/')
        self.assertEqual(response.status_code, 403)

    def test_delete_cluster(self):
        self.client.login(username='res_admin', password='pw')
        cluster = GPUCluster.objects_unscoped.create(organization=self.org, name='to-delete')
        response = self.client.post(f'/settings/resources/clusters/{cluster.id}/delete/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GPUCluster.objects_unscoped.filter(pk=cluster.id).exists())


class MembersPageTest(TestCase):
    def setUp(self):
        self.admin, self.org = _make_user_and_org('mem_admin', role='owner')
        self.member = User.objects.create_user(username='mem_alice', password='pw')
        self.member.profile.organization = self.org
        self.member.profile.role = 'viewer'
        self.member.profile.save()

    @patch('monitor.views.settings_views.send_mail')
    def test_invite_creates_invite_row_and_sends_email(self, mock_send):
        self.client.login(username='mem_admin', password='pw')
        response = self.client.post('/settings/members/invite/', {
            'email': 'new@example.com',
            'role': 'viewer',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Invite.objects.filter(email='new@example.com', organization=self.org).exists())
        self.assertTrue(mock_send.called)

    def test_change_member_role(self):
        self.client.login(username='mem_admin', password='pw')
        response = self.client.post(f'/settings/members/{self.member.id}/role/', {'role': 'admin'})
        self.assertEqual(response.status_code, 200)
        self.member.profile.refresh_from_db()
        self.assertEqual(self.member.profile.role, 'admin')

    def test_remove_member(self):
        self.client.login(username='mem_admin', password='pw')
        response = self.client.post(f'/settings/members/{self.member.id}/remove/')
        self.assertEqual(response.status_code, 200)
        self.member.profile.refresh_from_db()
        self.assertIsNone(self.member.profile.organization)

    def test_accept_invite_creates_user(self):
        invite = Invite.objects.create(
            organization=self.org,
            invited_by=self.admin,
            email='newguy@example.com',
            role='viewer',
        )
        response = self.client.post(f'/accounts/accept-invite/{invite.token}/', {
            'username': 'newguy',
            'password': 'securepass123',
            'password_confirm': 'securepass123',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        new_user = User.objects.get(username='newguy')
        self.assertEqual(new_user.profile.organization, self.org)
        self.assertEqual(new_user.profile.role, 'viewer')
        invite.refresh_from_db()
        self.assertIsNotNone(invite.accepted_at)
