from __future__ import annotations

import asyncio
from typing import Protocol

from app.core.models import InvestigationRequest


class SignalProvider(Protocol):
    async def get_pod_signals(self, request: InvestigationRequest) -> list[dict]: ...

    async def get_log_signals(self, request: InvestigationRequest) -> list[dict]: ...

    async def get_event_signals(self, request: InvestigationRequest) -> list[dict]: ...

    async def get_deployment_signals(self, request: InvestigationRequest) -> list[dict]: ...

    async def get_network_signals(self, request: InvestigationRequest) -> list[dict]: ...


class MockSignalProvider:
    async def get_pod_signals(self, request: InvestigationRequest) -> list[dict]:
        await asyncio.sleep(0.1)
        scenario = request.scenario or "crashloop-missing-env"
        mapping = {
            "crashloop-missing-env": [
                {
                    "name": "payment-service-7c9d6d6b78-9m2k2",
                    "namespace": request.namespace,
                    "phase": "Running",
                    "reason": "CrashLoopBackOff",
                    "restartCount": 18,
                }
            ],
            "image-pull-backoff": [
                {
                    "name": "payment-service-7c9d6d6b78-xk9lp",
                    "namespace": request.namespace,
                    "phase": "Pending",
                    "reason": "ImagePullBackOff",
                    "restartCount": 0,
                }
            ],
            "oomkilled": [
                {
                    "name": "worker-66f8f7994-2fhk7",
                    "namespace": request.namespace,
                    "phase": "Running",
                    "reason": "OOMKilled",
                    "restartCount": 6,
                }
            ],
            "pending-resource": [
                {
                    "name": "api-6d5478d7ff-v8n2f",
                    "namespace": request.namespace,
                    "phase": "Pending",
                    "reason": "Unschedulable",
                    "restartCount": 0,
                }
            ],
            "service-selector-mismatch": [
                {
                    "name": "frontend-54f6764b88-h7bkk",
                    "namespace": request.namespace,
                    "phase": "Running",
                    "reason": "Ready",
                    "restartCount": 0,
                }
            ],
            "dns-failure": [
                {
                    "name": "orders-6c8f7cb5f8-5twqk",
                    "namespace": request.namespace,
                    "phase": "Running",
                    "reason": "Ready",
                    "restartCount": 0,
                }
            ],
        }
        return mapping.get(scenario, mapping["crashloop-missing-env"])

    async def get_log_signals(self, request: InvestigationRequest) -> list[dict]:
        await asyncio.sleep(0.1)
        scenario = request.scenario or "crashloop-missing-env"
        mapping = {
            "crashloop-missing-env": [
                {
                    "pod": "payment-service-7c9d6d6b78-9m2k2",
                    "container": "payment-service",
                    "lines": [
                        "Starting payment service...",
                        "FATAL: DATABASE_URL environment variable missing",
                        "Exiting with status code 1",
                    ],
                }
            ],
            "image-pull-backoff": [
                {
                    "pod": "payment-service-7c9d6d6b78-xk9lp",
                    "container": "payment-service",
                    "lines": [
                        "Back-off pulling image \"registry.example.com/payment:bad-tag\"",
                    ],
                }
            ],
            "oomkilled": [
                {
                    "pod": "worker-66f8f7994-2fhk7",
                    "container": "worker",
                    "lines": [
                        "Processing batch size=5000",
                        "Killed",
                    ],
                }
            ],
            "pending-resource": [
                {
                    "pod": "api-6d5478d7ff-v8n2f",
                    "container": "api",
                    "lines": [
                        "No logs yet: pod not scheduled",
                    ],
                }
            ],
            "service-selector-mismatch": [
                {
                    "pod": "frontend-54f6764b88-h7bkk",
                    "container": "frontend",
                    "lines": [
                        "Failed to call payment service: connection refused",
                    ],
                }
            ],
            "dns-failure": [
                {
                    "pod": "orders-6c8f7cb5f8-5twqk",
                    "container": "orders",
                    "lines": [
                        "dial tcp: lookup payment.default.svc.cluster.local: no such host",
                    ],
                }
            ],
        }
        return mapping.get(scenario, mapping["crashloop-missing-env"])

    async def get_event_signals(self, request: InvestigationRequest) -> list[dict]:
        await asyncio.sleep(0.1)
        scenario = request.scenario or "crashloop-missing-env"
        mapping = {
            "crashloop-missing-env": [
                {
                    "type": "Warning",
                    "reason": "BackOff",
                    "message": "Back-off restarting failed container payment-service",
                }
            ],
            "image-pull-backoff": [
                {
                    "type": "Warning",
                    "reason": "Failed",
                    "message": "Failed to pull image \"registry.example.com/payment:bad-tag\"",
                }
            ],
            "oomkilled": [
                {
                    "type": "Warning",
                    "reason": "OOMKilled",
                    "message": "Container worker was OOMKilled",
                }
            ],
            "pending-resource": [
                {
                    "type": "Warning",
                    "reason": "FailedScheduling",
                    "message": "0/5 nodes are available: 5 Insufficient memory.",
                }
            ],
            "service-selector-mismatch": [
                {
                    "type": "Warning",
                    "reason": "Unhealthy",
                    "message": "Readiness probe failed: no upstream endpoints",
                }
            ],
            "dns-failure": [
                {
                    "type": "Warning",
                    "reason": "DNSConfigForming",
                    "message": "DNS resolution failed for service payment.default.svc.cluster.local",
                }
            ],
        }
        return mapping.get(scenario, mapping["crashloop-missing-env"])

    async def get_deployment_signals(self, request: InvestigationRequest) -> list[dict]:
        await asyncio.sleep(0.1)
        scenario = request.scenario or "crashloop-missing-env"
        base = {
            "name": request.target or "payment-service",
            "namespace": request.namespace,
            "desired": 3,
            "available": 1,
            "updated": 1,
            "rollout": "Degraded",
        }
        if scenario == "service-selector-mismatch":
            base["available"] = 3
            base["updated"] = 3
            base["rollout"] = "Healthy"
        if scenario == "pending-resource":
            base["available"] = 0
            base["updated"] = 0
            base["rollout"] = "Stalled"
        return [base]

    async def get_network_signals(self, request: InvestigationRequest) -> list[dict]:
        await asyncio.sleep(0.1)
        scenario = request.scenario or "crashloop-missing-env"
        mapping = {
            "crashloop-missing-env": [
                {
                    "service": "payment-service",
                    "selector": "app=payment",
                    "endpointCount": 0,
                    "dns": "ok",
                }
            ],
            "image-pull-backoff": [
                {
                    "service": "payment-service",
                    "selector": "app=payment",
                    "endpointCount": 0,
                    "dns": "ok",
                }
            ],
            "oomkilled": [
                {
                    "service": "worker",
                    "selector": "app=worker",
                    "endpointCount": 1,
                    "dns": "ok",
                }
            ],
            "pending-resource": [
                {
                    "service": "api",
                    "selector": "app=api",
                    "endpointCount": 0,
                    "dns": "ok",
                }
            ],
            "service-selector-mismatch": [
                {
                    "service": "payment-service",
                    "selector": "app=payment-v2",
                    "endpointCount": 0,
                    "dns": "ok",
                }
            ],
            "dns-failure": [
                {
                    "service": "payment-service",
                    "selector": "app=payment",
                    "endpointCount": 3,
                    "dns": "failed",
                }
            ],
        }
        return mapping.get(scenario, mapping["crashloop-missing-env"])
