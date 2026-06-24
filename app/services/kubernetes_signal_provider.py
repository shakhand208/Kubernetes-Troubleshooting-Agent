from __future__ import annotations

import asyncio
import base64
import json
import tempfile
from pathlib import Path
from typing import Any

import yaml
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.stream import stream

from app.core.models import InvestigationRequest


class RealKubernetesSignalProvider:
    def __init__(self, kubeconfig_content: str) -> None:
        self.kubeconfig_content = kubeconfig_content
        self._setup_client()

    def _setup_client(self) -> None:
        """Load kubeconfig and initialize Kubernetes client."""
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                f.write(self.kubeconfig_content)
                kubeconfig_path = f.name

            k8s_config.load_kube_config(config_file=kubeconfig_path)
            self.v1_api = k8s_client.CoreV1Api()
            self.apps_api = k8s_client.AppsV1Api()
            self.batch_api = k8s_client.BatchV1Api()
            Path(kubeconfig_path).unlink()
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize Kubernetes client: {exc}")

    async def get_pod_signals(self, request: InvestigationRequest) -> list[dict]:
        """Get pod health and status signals."""
        await asyncio.sleep(0.1)
        try:
            pods = self.v1_api.list_namespaced_pod(request.namespace)
            signals = []
            print(f"[DEBUG] get_pod_signals - namespace={request.namespace}, target={request.target}, workload_type={request.workload_type}")
            for pod in pods.items:
                # Filter by target pod name if specified
                if request.target and request.target != pod.metadata.name:
                    continue
                
                container_statuses = pod.status.container_statuses or []
                restart_count = sum(s.restart_count for s in container_statuses)
                reason = "Running"
                if pod.status.phase != "Running":
                    reason = pod.status.phase
                elif any(s.state.waiting for s in container_statuses):
                    reason = container_statuses[0].state.waiting.reason or "Waiting"
                elif any(s.state.terminated for s in container_statuses):
                    reason = container_statuses[0].state.terminated.reason or "Terminated"

                signals.append(
                    {
                        "name": pod.metadata.name,
                        "namespace": request.namespace,
                        "phase": pod.status.phase,
                        "reason": reason,
                        "restartCount": restart_count,
                    }
                )
            print(f"[DEBUG] get_pod_signals - returned {len(signals)} pods")
            return signals
        except Exception as exc:
            print(f"Failed to get pod signals: {exc}")
            return []

    async def get_log_signals(self, request: InvestigationRequest) -> list[dict]:
        """Get container logs from pods."""
        await asyncio.sleep(0.1)
        signals = []
        try:
            pods = self.v1_api.list_namespaced_pod(request.namespace)
            for pod in pods.items:
                if request.target and request.target not in pod.metadata.name:
                    continue

                for container in pod.spec.containers:
                    try:
                        logs = self.v1_api.read_namespaced_pod_log(
                            pod.metadata.name,
                            request.namespace,
                            container=container.name,
                            tail_lines=50,
                        )
                        if logs.strip():
                            signals.append(
                                {
                                    "pod": pod.metadata.name,
                                    "container": container.name,
                                    "lines": logs.split("\n")[-10:],
                                }
                            )
                    except Exception:
                        pass
            return signals
        except Exception as exc:
            print(f"Failed to get log signals: {exc}")
            return []

    async def get_event_signals(self, request: InvestigationRequest) -> list[dict]:
        """Get Kubernetes events for namespace."""
        await asyncio.sleep(0.1)
        signals = []
        try:
            events = self.v1_api.list_namespaced_event(request.namespace)
            for event in events.items:
                # If a specific pod is selected, only include events for that pod or its deployment
                if request.target:
                    involved = event.involved_object.name
                    if involved != request.target:
                        continue
                
                signals.append(
                    {
                        "type": event.type,
                        "reason": event.reason,
                        "message": event.message,
                        "involved_object": event.involved_object.kind + "/" + event.involved_object.name,
                    }
                )
            return signals[-20:]
        except Exception as exc:
            print(f"Failed to get event signals: {exc}")
            return []

    async def get_deployment_signals(self, request: InvestigationRequest) -> list[dict]:
        """Get deployment rollout status."""
        await asyncio.sleep(0.1)
        signals = []
        try:
            deployments = self.apps_api.list_namespaced_deployment(request.namespace)
            
            print(f"\n{'='*60}")
            print(f"[DEBUG] GET_DEPLOYMENT_SIGNALS")
            print(f"{'='*60}")
            print(f"request.target: {request.target}")
            print(f"request.workload_type: {request.workload_type}")
            print(f"Total deployments in namespace: {len(deployments.items)}")
            
            # Skip deployment analysis for non-deployment workload types
            # These types have their own specific signals we should focus on instead
            if request.workload_type in ["pods", "statefulsets", "daemonsets", "jobs"]:
                print(f"[MODE] {request.workload_type.upper()} MODE - skipping deployment analysis")
                print(f"[INFO] Focusing on {request.workload_type}-specific signals instead")
                print(f"{'='*60}\n")
                return []
            
            # For deployments or when workload_type is not specified, analyze deployments
            # Determine which deployments to include
            target_deployment = None
            if request.target and request.workload_type == "deployments":
                print(f"[MODE] DEPLOYMENT MODE - filtering to deployment '{request.target}'")
                target_deployment = request.target
            elif request.target:
                print(f"[MODE] FILTERING MODE - looking for deployment with target '{request.target}'")
                target_deployment = request.target
            else:
                print(f"[MODE] NO TARGET - returning all deployments")
            
            # Filter deployments
            print(f"[FILTER] Filtering deployments (target_deployment={target_deployment})")
            for deploy in deployments.items:
                # If we have a target deployment, only include that one
                if target_deployment and deploy.metadata.name != target_deployment:
                    print(f"[SKIP] Skipping deployment {deploy.metadata.name} (not target)")
                    continue
                
                print(f"[INCLUDE] Including deployment {deploy.metadata.name}")
                status = deploy.status
                available = status.available_replicas or 0
                desired = deploy.spec.replicas or 0
                updated = status.updated_replicas or 0
                rollout = "Healthy" if available == desired else "Degraded"

                signals.append(
                    {
                        "name": deploy.metadata.name,
                        "namespace": request.namespace,
                        "desired": desired,
                        "available": available,
                        "updated": updated,
                        "rollout": rollout,
                    }
                )
            
            print(f"[RESULT] Returning {len(signals)} deployments")
            print(f"{'='*60}\n")
            return signals
        except Exception as exc:
            print(f"[ERROR] Failed to get deployment signals: {exc}")
            print(f"{'='*60}\n")
            return []

    async def get_network_signals(self, request: InvestigationRequest) -> list[dict]:
        """Get service and endpoint signals."""
        await asyncio.sleep(0.1)
        signals = []
        try:
            services = self.v1_api.list_namespaced_service(request.namespace)
            for svc in services.items:
                try:
                    endpoints = self.v1_api.read_namespaced_endpoints(svc.metadata.name, request.namespace)
                    endpoint_count = sum(len(subset.addresses or []) for subset in endpoints.subsets or [])
                except Exception:
                    endpoint_count = 0

                signals.append(
                    {
                        "service": svc.metadata.name,
                        "selector": json.dumps(svc.spec.selector or {}),
                        "endpointCount": endpoint_count,
                        "dns": "ok",
                    }
                )
            return signals
        except Exception as exc:
            print(f"Failed to get network signals: {exc}")
            return []

    async def get_statefulset_signals(self, request: InvestigationRequest) -> list[dict]:
        """Get StatefulSet rollout status."""
        await asyncio.sleep(0.1)
        signals = []
        try:
            statefulsets = self.apps_api.list_namespaced_stateful_set(request.namespace)
            
            print(f"\n{'='*60}")
            print(f"[DEBUG] GET_STATEFULSET_SIGNALS")
            print(f"{'='*60}")
            print(f"request.target: {request.target}")
            print(f"Total StatefulSets in namespace: {len(statefulsets.items)}")
            
            target_ss = request.target if request.target and request.workload_type == "statefulsets" else None
            
            for ss in statefulsets.items:
                if target_ss and ss.metadata.name != target_ss:
                    continue
                
                status = ss.status
                ready = status.ready_replicas or 0
                desired = ss.spec.replicas or 0
                health = "Healthy" if ready == desired else "Degraded"
                
                signals.append({
                    "name": ss.metadata.name,
                    "namespace": request.namespace,
                    "desired": desired,
                    "ready": ready,
                    "health": health,
                })
            
            print(f"[RESULT] Returning {len(signals)} StatefulSets")
            print(f"{'='*60}\n")
            return signals
        except Exception as exc:
            print(f"[ERROR] Failed to get StatefulSet signals: {exc}")
            print(f"{'='*60}\n")
            return []

    async def get_daemonset_signals(self, request: InvestigationRequest) -> list[dict]:
        """Get DaemonSet rollout status."""
        await asyncio.sleep(0.1)
        signals = []
        try:
            daemonsets = self.apps_api.list_namespaced_daemon_set(request.namespace)
            
            print(f"\n{'='*60}")
            print(f"[DEBUG] GET_DAEMONSET_SIGNALS")
            print(f"{'='*60}")
            print(f"request.target: {request.target}")
            print(f"Total DaemonSets in namespace: {len(daemonsets.items)}")
            
            target_ds = request.target if request.target and request.workload_type == "daemonsets" else None
            
            for ds in daemonsets.items:
                if target_ds and ds.metadata.name != target_ds:
                    continue
                
                status = ds.status
                ready = status.number_ready or 0
                desired = status.desired_number_scheduled or 0
                health = "Healthy" if ready == desired else "Degraded"
                
                signals.append({
                    "name": ds.metadata.name,
                    "namespace": request.namespace,
                    "desired": desired,
                    "ready": ready,
                    "health": health,
                })
            
            print(f"[RESULT] Returning {len(signals)} DaemonSets")
            print(f"{'='*60}\n")
            return signals
        except Exception as exc:
            print(f"[ERROR] Failed to get DaemonSet signals: {exc}")
            print(f"{'='*60}\n")
            return []

    async def get_job_signals(self, request: InvestigationRequest) -> list[dict]:
        """Get Job completion status."""
        await asyncio.sleep(0.1)
        signals = []
        try:
            jobs = self.batch_api.list_namespaced_job(request.namespace)
            
            print(f"\n{'='*60}")
            print(f"[DEBUG] GET_JOB_SIGNALS")
            print(f"{'='*60}")
            print(f"request.target: {request.target}")
            print(f"Total Jobs in namespace: {len(jobs.items)}")
            
            target_job = request.target if request.target and request.workload_type == "jobs" else None
            
            for job in jobs.items:
                if target_job and job.metadata.name != target_job:
                    continue
                
                status = job.status
                succeeded = status.succeeded or 0
                failed = status.failed or 0
                active = status.active or 0
                completions = job.spec.completions or 1
                health = "Completed" if succeeded > 0 else ("Failed" if failed > 0 else "Running")
                
                signals.append({
                    "name": job.metadata.name,
                    "namespace": request.namespace,
                    "desired": completions,
                    "succeeded": succeeded,
                    "failed": failed,
                    "active": active,
                    "status": health,
                })
            
            print(f"[RESULT] Returning {len(signals)} Jobs")
            print(f"{'='*60}\n")
            return signals
        except Exception as exc:
            print(f"[ERROR] Failed to get Job signals: {exc}")
            print(f"{'='*60}\n")
            return []

    async def get_namespaces(self) -> list[dict]:
        """Get all namespaces in the cluster."""
        try:
            namespaces = self.v1_api.list_namespace()
            return [
                {
                    "name": ns.metadata.name,
                    "phase": ns.status.phase,
                }
                for ns in namespaces.items
            ]
        except Exception as exc:
            print(f"Failed to get namespaces: {exc}")
            return []

    async def get_workloads(self, namespace: str) -> dict[str, Any]:
        """Get all workloads (pods, deployments, statefulsets, daemonsets, jobs) in a namespace."""
        try:
            workloads = {
                "pods": [],
                "deployments": [],
                "statefulsets": [],
                "daemonsets": [],
                "jobs": [],
            }

            # Get Pods
            try:
                pods = self.v1_api.list_namespaced_pod(namespace)
                for pod in pods.items:
                    workloads["pods"].append({
                        "name": pod.metadata.name,
                        "status": pod.status.phase,
                        "restarts": sum(s.restart_count for s in (pod.status.container_statuses or [])),
                    })
            except Exception as e:
                print(f"Failed to get pods: {e}")

            # Get Deployments
            try:
                deployments = self.apps_api.list_namespaced_deployment(namespace)
                for dep in deployments.items:
                    ready = dep.status.ready_replicas or 0
                    desired = dep.spec.replicas or 0
                    workloads["deployments"].append({
                        "name": dep.metadata.name,
                        "replicas": f"{ready}/{desired}",
                        "status": "Ready" if ready == desired else "Pending",
                    })
            except Exception as e:
                print(f"Failed to get deployments: {e}")

            # Get StatefulSets
            try:
                statefulsets = self.apps_api.list_namespaced_stateful_set(namespace)
                for sts in statefulsets.items:
                    ready = sts.status.ready_replicas or 0
                    desired = sts.spec.replicas or 0
                    workloads["statefulsets"].append({
                        "name": sts.metadata.name,
                        "replicas": f"{ready}/{desired}",
                        "status": "Ready" if ready == desired else "Pending",
                    })
            except Exception as e:
                print(f"Failed to get statefulsets: {e}")

            # Get DaemonSets
            try:
                daemonsets = self.apps_api.list_namespaced_daemon_set(namespace)
                for ds in daemonsets.items:
                    ready = ds.status.number_ready or 0
                    desired = ds.status.desired_number_scheduled or 0
                    workloads["daemonsets"].append({
                        "name": ds.metadata.name,
                        "replicas": f"{ready}/{desired}",
                        "status": "Ready" if ready == desired else "Pending",
                    })
            except Exception as e:
                print(f"Failed to get daemonsets: {e}")

            # Get Jobs
            try:
                batch_api = k8s_client.BatchV1Api()
                jobs = batch_api.list_namespaced_job(namespace)
                for job in jobs.items:
                    succeeded = job.status.succeeded or 0
                    completions = job.spec.completions or 0
                    workloads["jobs"].append({
                        "name": job.metadata.name,
                        "completions": f"{succeeded}/{completions}",
                        "status": "Complete" if succeeded == completions else "Running",
                    })
            except Exception as e:
                print(f"Failed to get jobs: {e}")

            return workloads
        except Exception as exc:
            print(f"Failed to get workloads: {exc}")
            return {}
