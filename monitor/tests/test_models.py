"""
monitor/tests/test_models.py -- Unit tests for Organization and GPU topology models.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from monitor.models import (
    APIKey,
    GPU,
    GPUCluster,
    GPUNode,
    Organization,
    Team,
    UserProfile,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_org(suffix='', plan='free'):
    """Create a user + organization for test fixtures."""
    username = f'testuser{suffix}'
    user = User.objects.create_user(username=username, password='testpass123')
    org = Organization.objects.create(
        name=f'Test Org{suffix}',
        slug=f'test-org{suffix}',
        owner=user,
        plan=plan,
    )
    return user, org


def make_cluster(org, name='Cluster-1', cloud='on_prem'):
    return GPUCluster.objects.create(
        organization=org,
        name=name,
        cloud=cloud,
    )


def make_node(cluster, org, hostname='worker-01', gpu_count=8):
    return GPUNode.objects.create(
        cluster=cluster,
        organization=org,
        hostname=hostname,
        gpu_count=gpu_count,
        gpu_type='NVIDIA A100-SXM4-80GB',
        gpu_memory_gb=80,
    )


# ── Test: Organization ────────────────────────────────────────────────────────

class OrganizationModelTest(TestCase):

    def test_create_organization_and_str(self):
        """Organization can be created and __str__ returns the name."""
        _, org = make_org()
        self.assertEqual(str(org), 'Test Org')

    def test_organization_plan_default(self):
        """Organization defaults to free plan."""
        _, org = make_org(suffix='2')
        self.assertEqual(org.plan, 'free')

    def test_organization_slug_unique(self):
        """Two organizations cannot share a slug."""
        from django.db import IntegrityError
        make_org(suffix='3')
        with self.assertRaises(IntegrityError):
            user2 = User.objects.create_user(username='dupuser', password='x')
            Organization.objects.create(
                name='Dup Org',
                slug='test-org3',
                owner=user2,
            )


# ── Test: Team ────────────────────────────────────────────────────────────────

class TeamModelTest(TestCase):

    def setUp(self):
        self.user, self.org = make_org(suffix='t')

    def test_create_team_and_str(self):
        team = Team.objects.create(
            organization=self.org,
            name='ML Platform',
            slug='ml-platform',
        )
        self.assertIn('ml-platform', str(team))
        self.assertIn(self.org.slug, str(team))

    def test_team_unique_slug_per_org(self):
        from django.db import IntegrityError
        Team.objects.create(organization=self.org, name='Team A', slug='team-a')
        with self.assertRaises(IntegrityError):
            Team.objects.create(organization=self.org, name='Team A2', slug='team-a')


# ── Test: UserProfile signal ──────────────────────────────────────────────────

class UserProfileSignalTest(TestCase):

    def test_profile_created_on_user_create(self):
        """post_save signal should auto-create a UserProfile for every new User."""
        user = User.objects.create_user(username='sigtest', password='pass')
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_profile_has_default_viewer_role(self):
        user = User.objects.create_user(username='roletest', password='pass')
        self.assertEqual(user.profile.role, 'viewer')


# ── Test: APIKey ──────────────────────────────────────────────────────────────

class APIKeyModelTest(TestCase):

    def setUp(self):
        self.user, self.org = make_org(suffix='k')

    def test_create_key_and_authenticate(self):
        """create_key returns (APIKey, raw_key); authenticate(raw_key) returns the key."""
        api_key, raw_key = APIKey.create_key(
            organization=self.org,
            user=self.user,
            name='Agent Key',
            scopes=['ingest', 'read'],
        )
        self.assertIsNotNone(api_key.pk)
        self.assertEqual(api_key.key_prefix, raw_key[:8])
        self.assertTrue(api_key.active)

        # authenticate with the correct raw key
        result = APIKey.authenticate(raw_key)
        self.assertIsNotNone(result)
        self.assertEqual(result.pk, api_key.pk)
        self.assertIsNotNone(result.last_used_at)

    def test_authenticate_invalid_key_returns_none(self):
        """authenticate should return None for a key that doesn't exist."""
        APIKey.create_key(organization=self.org, user=self.user, name='Key2')
        result = APIKey.authenticate('totally-invalid-key-string')
        self.assertIsNone(result)

    def test_authenticate_inactive_key_returns_none(self):
        """Deactivating a key should cause authenticate to return None."""
        api_key, raw_key = APIKey.create_key(
            organization=self.org, user=self.user, name='Deactivated',
        )
        api_key.active = False
        api_key.save()
        self.assertIsNone(APIKey.authenticate(raw_key))

    def test_authenticate_expired_key_returns_none(self):
        """An expired key (expires_at in the past) should not authenticate."""
        from django.utils import timezone
        import datetime
        past = timezone.now() - datetime.timedelta(hours=1)
        api_key, raw_key = APIKey.create_key(
            organization=self.org, user=self.user,
            name='Expired', expires_at=past,
        )
        self.assertIsNone(APIKey.authenticate(raw_key))

    def test_create_key_str(self):
        api_key, raw_key = APIKey.create_key(
            organization=self.org, user=self.user, name='Str Test',
        )
        self.assertIn(api_key.key_prefix, str(api_key))
        self.assertIn('Str Test', str(api_key))


# ── Test: GPUNode ─────────────────────────────────────────────────────────────

class GPUNodeModelTest(TestCase):

    def setUp(self):
        self.user, self.org = make_org(suffix='n')
        self.cluster = make_cluster(self.org)

    def test_create_gpunode_and_str(self):
        node = make_node(self.cluster, self.org)
        self.assertIn('worker-01', str(node))
        self.assertIn('8', str(node))

    def test_gpunode_default_status(self):
        node = make_node(self.cluster, self.org, hostname='worker-02')
        self.assertEqual(node.status, 'active')

    def test_gpunode_unique_hostname_per_org(self):
        from django.db import IntegrityError
        make_node(self.cluster, self.org, hostname='uniq-host')
        with self.assertRaises(IntegrityError):
            make_node(self.cluster, self.org, hostname='uniq-host')


# ── Test: GPU ─────────────────────────────────────────────────────────────────

class GPUModelTest(TestCase):

    def setUp(self):
        self.user, self.org = make_org(suffix='g')
        self.cluster = make_cluster(self.org)
        self.node = make_node(self.cluster, self.org)

    def _make_gpu(self, index=0, utilization=50.0, mem_used=40960, mem_total=81920,
                  status='healthy', uuid=None):
        if uuid is None:
            uuid = f'GPU-test-{index}-{self.node.hostname}'
        return GPU.objects.create(
            node=self.node,
            organization=self.org,
            gpu_index=index,
            uuid=uuid,
            current_utilization=utilization,
            current_memory_used_mb=mem_used,
            current_memory_total_mb=mem_total,
            current_model_name='NVIDIA A100-SXM4-80GB',
            status=status,
        )

    def test_create_gpu_and_str(self):
        gpu = self._make_gpu(index=0)
        self.assertIn('A100', str(gpu))
        self.assertIn('worker-01', str(gpu))
        self.assertIn('[0]', str(gpu))

    def test_memory_utilization_pct(self):
        """memory_utilization_pct computes correctly from used/total."""
        gpu = self._make_gpu(mem_used=40960, mem_total=81920)
        self.assertAlmostEqual(gpu.memory_utilization_pct, 50.0, places=1)

    def test_memory_utilization_pct_none_when_missing(self):
        gpu = GPU.objects.create(
            node=self.node,
            organization=self.org,
            gpu_index=1,
            uuid='GPU-no-mem',
            current_model_name='A100',
        )
        self.assertIsNone(gpu.memory_utilization_pct)

    def test_is_idle_when_low_utilization(self):
        """GPU with utilization < 5% and status=healthy is considered idle."""
        gpu = self._make_gpu(index=2, utilization=1.0, status='healthy')
        self.assertTrue(gpu.is_idle)

    def test_is_idle_false_when_busy(self):
        """GPU with utilization >= 5% is not idle."""
        gpu = self._make_gpu(index=3, utilization=80.0, status='healthy')
        self.assertFalse(gpu.is_idle)

    def test_is_idle_false_when_degraded(self):
        """A degraded GPU is not considered idle even with low utilization."""
        gpu = self._make_gpu(index=4, utilization=0.5, status='degraded')
        self.assertFalse(gpu.is_idle)

    def test_is_idle_false_when_no_utilization(self):
        """is_idle returns False if current_utilization is None."""
        gpu = GPU.objects.create(
            node=self.node,
            organization=self.org,
            gpu_index=5,
            uuid='GPU-null-util',
            current_model_name='A100',
            status='healthy',
        )
        self.assertFalse(gpu.is_idle)

    def test_gpu_unique_index_per_node(self):
        """Two GPUs on the same node cannot share the same device index."""
        from django.db import IntegrityError
        self._make_gpu(index=6, uuid='GPU-dup-a')
        with self.assertRaises(IntegrityError):
            self._make_gpu(index=6, uuid='GPU-dup-b')

    def test_gpu_uuid_unique(self):
        """UUID must be globally unique."""
        from django.db import IntegrityError
        self._make_gpu(index=7, uuid='GPU-same-uuid')
        with self.assertRaises(IntegrityError):
            GPU.objects.create(
                node=self.node,
                organization=self.org,
                gpu_index=8,
                uuid='GPU-same-uuid',
                current_model_name='A100',
            )
