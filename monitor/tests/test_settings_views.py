# monitor/tests/test_settings_views.py
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from monitor.models import Organization, GPUCluster, GPUNode


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
        from monitor.models import Invite
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
