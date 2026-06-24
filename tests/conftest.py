#!/usr/bin/env python3
"""
Test fixtures and helper functions for pytest
"""

import pytest
import asyncio
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import Mock, AsyncMock, patch

from app.core.models import InvestigationRequest, SignalBundle, InvestigationReport
from app.services.investigation_service import InvestigationService


# ============================================================================
# MOCK KUBERNETES CONFIG
# ============================================================================

MOCK_KUBECONFIG = """
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: LS0tLS1CRUdJTi...
    server: https://mock-cluster.eastus.azmk8s.io:443
  name: mock-cluster
contexts:
- context:
    cluster: mock-cluster
    user: clusterUser_mock-rg_mock-cluster
  name: mock-cluster
current-context: mock-cluster
kind: Config
preferences: {}
users:
- name: clusterUser_mock-rg_mock-cluster
  user:
    client-certificate-data: LS0tLS1CRUdJTi...
    client-key-data: LS0tLS1CRUdJTi...
    token: mock-token-12345
"""


# ============================================================================
# MOCK DATA FACTORIES
# ============================================================================

def create_mock_pod(
    name: str = "test-pod",
    phase: str = "Running",
    restart_count: int = 0,
    namespace: str = "default"
) -> Dict[str, Any]:
    """Create mock pod signal data."""
    return {
        "name": name,
        "namespace": namespace,
        "phase": phase,
        "restart_count": restart_count,
        "ready": phase == "Running"
    }


def create_mock_deployment(
    name: str = "test-deployment",
    desired: int = 3,
    ready: int = 3,
    updated: int = 3,
    namespace: str = "default"
) -> Dict[str, Any]:
    """Create mock deployment signal data."""
    return {
        "name": name,
        "namespace": namespace,
        "desired": desired,
        "ready": ready,
        "updated": updated,
        "health": "Healthy" if ready == desired else "Degraded"
    }


def create_mock_statefulset(
    name: str = "test-statefulset",
    desired: int = 3,
    ready: int = 3,
    namespace: str = "default"
) -> Dict[str, Any]:
    """Create mock StatefulSet signal data."""
    return {
        "name": name,
        "namespace": namespace,
        "desired": desired,
        "ready": ready,
        "health": "Healthy" if ready == desired else "Degraded"
    }


def create_mock_daemonset(
    name: str = "test-daemonset",
    desired: int = 5,
    ready: int = 5,
    namespace: str = "default"
) -> Dict[str, Any]:
    """Create mock DaemonSet signal data."""
    return {
        "name": name,
        "namespace": namespace,
        "desired": desired,
        "ready": ready,
        "health": "Healthy" if ready == desired else "Degraded"
    }


def create_mock_job(
    name: str = "test-job",
    succeeded: int = 1,
    failed: int = 0,
    active: int = 0,
    status: str = "Completed",
    namespace: str = "default"
) -> Dict[str, Any]:
    """Create mock Job signal data."""
    return {
        "name": name,
        "namespace": namespace,
        "succeeded": succeeded,
        "failed": failed,
        "active": active,
        "status": status
    }


def create_mock_log(
    pod: str = "test-pod",
    container: str = "app",
    log_lines: List[str] = None
) -> Dict[str, Any]:
    """Create mock log signal data."""
    if log_lines is None:
        log_lines = ["Container started", "Application ready"]
    
    return {
        "pod": pod,
        "container": container,
        "log_lines": log_lines
    }


def create_mock_event(
    message: str = "Pod started",
    reason: str = "Created",
    obj_type: str = "Pod",
    obj_name: str = "test-pod"
) -> Dict[str, Any]:
    """Create mock event signal data."""
    return {
        "message": message,
        "reason": reason,
        "object_type": obj_type,
        "object_name": obj_name
    }


# ============================================================================
# MOCK SIGNAL PROVIDER
# ============================================================================

class MockSignalProvider:
    """Mock Kubernetes signal provider for testing."""

    def __init__(self):
        self.call_count = {
            'pod_signals': 0,
            'deployment_signals': 0,
            'statefulset_signals': 0,
            'daemonset_signals': 0,
            'job_signals': 0,
        }

    async def get_pod_signals(self, request: InvestigationRequest) -> List[Dict]:
        """Mock pod signals."""
        self.call_count['pod_signals'] += 1
        
        if request.target:
            return [create_mock_pod(name=request.target)]
        
        return [
            create_mock_pod("healthy-pod", "Running", 0),
            create_mock_pod("crashloop-pod", "CrashLoopBackOff", 5),
            create_mock_pod("pending-pod", "Pending", 0),
        ]

    async def get_deployment_signals(self, request: InvestigationRequest) -> List[Dict]:
        """Mock deployment signals."""
        self.call_count['deployment_signals'] += 1
        
        # Skip for non-deployment workload types
        if request.workload_type in ["pods", "statefulsets", "daemonsets", "jobs"]:
            return []
        
        if request.target:
            return [create_mock_deployment(name=request.target)]
        
        return [
            create_mock_deployment("healthy-deployment", 3, 3, 3),
            create_mock_deployment("degraded-deployment", 3, 1, 1),
        ]

    async def get_statefulset_signals(self, request: InvestigationRequest) -> List[Dict]:
        """Mock StatefulSet signals."""
        self.call_count['statefulset_signals'] += 1
        
        if request.target:
            return [create_mock_statefulset(name=request.target)]
        
        return [create_mock_statefulset("test-statefulset", 3, 3)]

    async def get_daemonset_signals(self, request: InvestigationRequest) -> List[Dict]:
        """Mock DaemonSet signals."""
        self.call_count['daemonset_signals'] += 1
        
        if request.target:
            return [create_mock_daemonset(name=request.target)]
        
        return [create_mock_daemonset("test-daemonset", 5, 5)]

    async def get_job_signals(self, request: InvestigationRequest) -> List[Dict]:
        """Mock Job signals."""
        self.call_count['job_signals'] += 1
        
        if request.target:
            return [create_mock_job(name=request.target)]
        
        return [
            create_mock_job("completed-job", 1, 0, 0, "Completed"),
            create_mock_job("failed-job", 0, 1, 0, "Failed"),
        ]

    async def get_log_signals(self, request: InvestigationRequest) -> List[Dict]:
        """Mock log signals."""
        return [
            create_mock_log(request.target or "test-pod", "app", 
                          ["Container started", "No errors"])
        ]

    async def get_event_signals(self, request: InvestigationRequest) -> List[Dict]:
        """Mock event signals."""
        return [
            create_mock_event("Pod started", "Created", "Pod", 
                            request.target or "test-pod")
        ]

    async def get_network_signals(self, request: InvestigationRequest) -> List[Dict]:
        """Mock network signals."""
        return [
            {
                "service": "test-service",
                "namespace": request.namespace,
                "endpoints": 3
            }
        ]

    async def get_namespaces(self) -> List[str]:
        """Mock namespace list."""
        return ["default", "kube-system", "test-troubleshooter"]


# ============================================================================
# MOCK AI AGENT
# ============================================================================

class MockAIAgent:
    """Mock AI agent for testing."""

    async def analyze(self, signals: SignalBundle) -> InvestigationReport:
        """Mock AI analysis."""
        
        # Simple heuristic-based analysis
        root_cause = "Unknown issue"
        confidence = 50
        recommended_fixes = ["Check logs", "Restart pod"]
        evidence = ["Signal data processed"]
        
        if signals.pods:
            for pod in signals.pods:
                if pod.get("phase") == "CrashLoopBackOff":
                    root_cause = "Application is crashing repeatedly"
                    confidence = 90
                    recommended_fixes = [
                        "Check container logs for errors",
                        "Verify environment variables",
                        "Check resource limits"
                    ]
                elif pod.get("phase") == "Pending":
                    root_cause = "Pod cannot be scheduled"
                    confidence = 85
                    recommended_fixes = [
                        "Check node availability",
                        "Check resource requests",
                        "Check taints/tolerations"
                    ]
        
        if signals.deployments:
            for dep in signals.deployments:
                if dep.get("ready", 0) < dep.get("desired", 1):
                    root_cause = f"Deployment replicas not ready ({dep['ready']}/{dep['desired']})"
                    confidence = 80
                    recommended_fixes = [
                        "Check pod logs",
                        "Check image availability",
                        "Check node resources"
                    ]
        
        return InvestigationReport(
            root_cause=root_cause,
            confidence=confidence,
            recommended_fixes=recommended_fixes,
            evidence=evidence,
            prevention=["Implement pod disruption budgets", "Set resource requests/limits"]
        )


# ============================================================================
# PYTEST FIXTURES
# ============================================================================

@pytest.fixture
def mock_signal_provider():
    """Provide mock signal provider."""
    return MockSignalProvider()


@pytest.fixture
def mock_ai_agent():
    """Provide mock AI agent."""
    return MockAIAgent()


@pytest.fixture
def investigation_service(mock_signal_provider, mock_ai_agent):
    """Provide investigation service with mocks."""
    service = InvestigationService(mock_signal_provider)
    service._ai_agent = mock_ai_agent
    return service


@pytest.fixture
def sample_investigation_request():
    """Provide sample investigation request."""
    return InvestigationRequest(
        incident_name="Test Investigation",
        namespace="default",
        target="test-pod",
        workload_type="pods"
    )


@pytest.fixture
def sample_signal_bundle():
    """Provide sample signal bundle."""
    return SignalBundle(
        pods=[create_mock_pod()],
        logs=[create_mock_log()],
        events=[create_mock_event()],
        deployments=[create_mock_deployment()],
        network=[{"service": "test-svc", "endpoints": 3}]
    )


@pytest.fixture
def sample_investigation_report():
    """Provide sample investigation report."""
    return InvestigationReport(
        root_cause="Test root cause",
        confidence=85,
        evidence=["Test evidence"],
        recommended_fixes=["Test fix"],
        prevention=["Test prevention"]
    )


# ============================================================================
# ASYNC TEST HELPER
# ============================================================================

@pytest.fixture
def event_loop():
    """Provide event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# PATCHING HELPERS
# ============================================================================

@pytest.fixture
def mock_kubernetes_client(monkeypatch):
    """Mock Kubernetes client."""
    mock_v1 = AsyncMock()
    mock_apps = AsyncMock()
    mock_batch = AsyncMock()
    
    # Mock pod listing
    mock_v1.list_namespaced_pod.return_value.items = [
        Mock(metadata=Mock(name="test-pod"))
    ]
    
    # Mock deployment listing
    mock_apps.list_namespaced_deployment.return_value.items = [
        Mock(metadata=Mock(name="test-deployment"))
    ]
    
    return {
        'v1_api': mock_v1,
        'apps_api': mock_apps,
        'batch_api': mock_batch
    }


@pytest.fixture
def mock_azure_auth(monkeypatch):
    """Mock Azure authentication."""
    mock_auth = Mock()
    mock_auth.is_authenticated.return_value = True
    mock_auth.get_current_account.return_value = {
        'id': 'test-subscription',
        'name': 'Test Account'
    }
    mock_auth.list_aks_clusters.return_value = [
        {
            'name': 'test-cluster',
            'resource_group': 'test-rg',
            'location': 'eastus'
        }
    ]
    mock_auth.get_cluster_credentials.return_value = {
        'kubeconfig': MOCK_KUBECONFIG
    }
    
    return mock_auth


# ============================================================================
# TEST DATA BUILDERS
# ============================================================================

class InvestigationRequestBuilder:
    """Builder for creating test investigation requests."""
    
    def __init__(self):
        self.incident_name = "Test Investigation"
        self.namespace = "default"
        self.target = None
        self.workload_type = None
        self.scenario = None
    
    def with_incident_name(self, name: str):
        self.incident_name = name
        return self
    
    def with_namespace(self, ns: str):
        self.namespace = ns
        return self
    
    def with_target(self, target: str):
        self.target = target
        return self
    
    def with_workload_type(self, wtype: str):
        self.workload_type = wtype
        return self
    
    def with_scenario(self, scenario: str):
        self.scenario = scenario
        return self
    
    def build(self) -> InvestigationRequest:
        return InvestigationRequest(
            incident_name=self.incident_name,
            namespace=self.namespace,
            target=self.target,
            workload_type=self.workload_type,
            scenario=self.scenario
        )


@pytest.fixture
def request_builder():
    """Provide investigation request builder."""
    return InvestigationRequestBuilder()


# ============================================================================
# PERFORMANCE TESTING HELPERS
# ============================================================================

import time
from contextlib import contextmanager

@contextmanager
def measure_execution_time(name: str = "Operation"):
    """Context manager to measure execution time."""
    start = time.time()
    print(f"\n⏱️  Starting {name}...")
    
    try:
        yield
    finally:
        elapsed = time.time() - start
        print(f"✅ {name} completed in {elapsed:.2f}s")


@pytest.fixture
def performance_tracker():
    """Track performance metrics."""
    class PerformanceTracker:
        def __init__(self):
            self.metrics = {}
        
        def record(self, name: str, duration: float):
            self.metrics[name] = duration
        
        def get_summary(self):
            return self.metrics
    
    return PerformanceTracker()
