# monitor/tests/test_settings_views.py
from django.test import TestCase
from django.urls import reverse


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
