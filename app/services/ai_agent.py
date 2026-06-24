from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from app.core.models import InvestigationReport, SignalBundle


class AIAgent:
    def __init__(self) -> None:
        self._api_key = os.getenv("OPENROUTER_API_KEY")
        self._model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

    async def analyze(self, signals: SignalBundle) -> InvestigationReport:
        if self._api_key:
            report = await self._analyze_with_openrouter(signals)
            if report:
                return report
        return self._deterministic_analysis(signals)

    async def _analyze_with_openrouter(self, signals: SignalBundle) -> InvestigationReport | None:
        prompt = self._build_prompt(signals)
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a Kubernetes SRE expert. Analyze logs and pod signals to identify root causes. Respond ONLY with valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/your-org/ai-kubernetes-troubleshooter",
            "X-Title": "AI Kubernetes Troubleshooter",
        }
        try:
            print(f"[DEBUG] Using LLM model: {self._model}")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                body = response.json()
            content = self._extract_content(body)
            print(f"[DEBUG] LLM response: {content[:200]}")
            parsed = self._safe_parse_json(content)
            if not parsed:
                print("[DEBUG] Failed to parse LLM response as JSON")
                return None
            
            # Validate required fields
            if not all(k in parsed for k in ["root_cause", "confidence", "evidence", "recommended_fixes", "prevention"]):
                print("[DEBUG] LLM response missing required fields")
                return None
            
            confidence_score = float(parsed.get("confidence", 55))
            print(f"[DEBUG] LLM analysis successful: {parsed.get('root_cause', '')[:80]}")
            print(f"[DEBUG] Confidence from LLM: {confidence_score}")
            return InvestigationReport(
                root_cause=parsed.get("root_cause", "Unknown root cause"),
                confidence=min(100, max(0, confidence_score)),
                evidence=parsed.get("evidence", []),
                recommended_fixes=parsed.get("recommended_fixes", []),
                prevention=parsed.get("prevention", []),
                resolution_steps=parsed.get("resolution_steps", []),
            )
        except httpx.HTTPStatusError as e:
            print(f"[DEBUG] LLM API error: {e.status_code} - {e.response.text[:200]}")
            return None
        except Exception as e:
            print(f"[DEBUG] LLM analysis failed: {e}")
            return None

    def _extract_content(self, body: dict[str, Any]) -> str:
        choices = body.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict)]
            return "\n".join(text_parts)
        return str(content)

    def _safe_parse_json(self, text: str) -> dict[str, Any] | None:
        text = text.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                return None
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

    def _get_workload_description(self, target: str | None) -> str:
        """Get a human-friendly description of the workload being investigated."""
        if not target:
            return "Cluster"
        
        # Check if target looks like a pod name (contains pod-hash pattern)
        if any(x in target.lower() for x in ["-6", "-7", "-8", "-9", "-", "pod"]):
            # Try to extract deployment name from pod name (e.g., service-7b7b887797-7nrfg -> service)
            parts = target.rsplit("-", 2)
            if len(parts) > 0:
                deployment_name = parts[0]
                return f"Pod '{target}'"  # Show full pod name, no truncation
        
        # If it looks like a deployment name, use that
        if "-" in target:
            return f"Deployment '{target}'"
        
        return f"Workload '{target}'"

    def _build_prompt(self, signals: SignalBundle) -> str:
        """Build a comprehensive prompt for LLM analysis with full context."""
        
        # Format pod signals
        pods_info = "**Pod Status:**\n"
        for pod in signals.pods:
            pods_info += f"- {pod['name']}: {pod['phase']} (reason: {pod['reason']}, restarts: {pod['restartCount']})\n"
        
        # Format logs
        logs_info = "**Container Logs:**\n"
        for log in signals.logs:
            log_snippet = log.get('log_snippet', '')[:500]  # First 500 chars
            logs_info += f"- Pod {log.get('pod_name', 'unknown')}: {log_snippet}\n"
        if not signals.logs:
            logs_info += "- No logs available\n"
        
        # Format events
        events_info = "**Kubernetes Events:**\n"
        for event in signals.events:
            events_info += f"- {event.get('reason', 'Unknown')}: {event.get('message', '')}\n"
        if not signals.events:
            events_info += "- No events available\n"
        
        # Format deployments
        deployments_info = "**Deployments:**\n"
        for dep in signals.deployments:
            deployments_info += f"- {dep['name']}: {dep['replicas']} replicas ({dep['status']})\n"
        if not signals.deployments:
            deployments_info += "- No deployments\n"
        
        # Format network - filter to only relevant services if investigating a specific pod
        network_info = "**Network & Services:**\n"
        
        # If investigating a specific pod, extract its service name
        target_service = None
        if signals.target:
            # Pod names follow pattern: service-name-hash-random
            # Extract service name by removing the last two segments (hash and random)
            parts = signals.target.rsplit("-", 2)
            if parts:
                target_service = parts[0].lower()
        
        # Filter network data
        relevant_services = []
        for svc in signals.network:
            service_name = svc.get('service', 'unknown').lower()
            
            # Include service if:
            # 1. Not investigating a specific pod (analyzing whole cluster), OR
            # 2. Service matches the target pod's service
            if not target_service or service_name == target_service:
                relevant_services.append(svc)
                network_info += f"- Service {svc.get('service', 'unknown')}: {svc.get('endpointCount', 0)} endpoints, DNS: {svc.get('dns', 'unknown')}\n"
        
        if not relevant_services:
            network_info += "- No relevant services\n"
        
        prompt = f"""You are a Kubernetes SRE expert. Analyze the following Kubernetes cluster signals and provide a detailed root cause analysis.

{pods_info}

{logs_info}

{events_info}

{deployments_info}

{network_info}

**Your Task:**
1. Analyze all available signals to identify the primary issue
2. Look for patterns in logs that indicate the root cause
3. Check pod phases, restart counts, and event messages for clues
4. Identify any deployment readiness issues
5. Check for network/service connectivity problems

**Response Format:**
You MUST respond ONLY with a valid JSON object (no markdown, no explanation) with these exact fields:
{{
    "root_cause": "A clear, concise description of the primary issue (2-3 sentences)",
    "confidence": 85,
    "evidence": [
        "Evidence point 1 from logs or pod status",
        "Evidence point 2",
        "Evidence point 3"
    ],
    "recommended_fixes": [
        "Specific fix 1 (be actionable and concrete)",
        "Specific fix 2",
        "Specific fix 3"
    ],
    "prevention": [
        "Prevention strategy 1",
        "Prevention strategy 2"
    ],
    "resolution_steps": [
        {{
            "step": 1,
            "action": "Brief description of action to take",
            "command": "kubectl command or specific steps to execute",
            "purpose": "Why we are taking this step",
            "expected_output": "What a successful execution looks like"
        }},
        {{
            "step": 2,
            "action": "Next action",
            "command": "kubectl command or specific steps",
            "purpose": "Why we do this step",
            "expected_output": "What success looks like"
        }}
    ]
}}

Confidence should be 0-100 based on how certain you are. Be conservative - use 60-80 for uncertain diagnoses."""
        
        return prompt

    def _deterministic_analysis(self, signals: SignalBundle) -> InvestigationReport:
        """Smart analysis based on actual signal patterns - prioritize pod/log issues over network."""
        text = json.dumps(signals.model_dump()).lower()
        
        # Determine workload type description for messaging
        workload_desc = self._get_workload_description(signals.target)
        
        # PRIORITY 0: If investigating a specific workload type, analyze that type FIRST
        # This ensures we report issues with the actual target being investigated
        
        # Check if we have workload-type-specific signals (deployments/statefulsets/daemonsets/jobs)
        # These are stored in signals.deployments for all workload types
        if signals.deployments:
            deployment_issues = self._analyze_deployments(signals.deployments)
            if deployment_issues:
                deployment_issues.sort(key=lambda x: x["confidence"], reverse=True)
                top_issue = deployment_issues[0]
                return InvestigationReport(
                    root_cause=top_issue["root_cause"],
                    confidence=top_issue["confidence"],
                    evidence=top_issue["evidence"],
                    recommended_fixes=top_issue["recommended_fixes"],
                    prevention=top_issue["prevention"],
                )
        
        # PRIORITY 1: Check pod signals for actual problems
        pod_issues = self._analyze_pods(signals.pods)
        if pod_issues:
            # Sort by confidence and return top issue
            pod_issues.sort(key=lambda x: x["confidence"], reverse=True)
            top_issue = pod_issues[0]
            return InvestigationReport(
                root_cause=top_issue["root_cause"],
                confidence=top_issue["confidence"],
                evidence=top_issue["evidence"],
                recommended_fixes=top_issue["recommended_fixes"],
                prevention=top_issue["prevention"],
            )
        
        # PRIORITY 2: Check logs for errors (this is often the source of truth)
        log_issues = self._analyze_logs(signals.logs)
        if log_issues:
            log_issues.sort(key=lambda x: x["confidence"], reverse=True)
            top_issue = log_issues[0]
            return InvestigationReport(
                root_cause=top_issue["root_cause"],
                confidence=top_issue["confidence"],
                evidence=top_issue["evidence"],
                recommended_fixes=top_issue["recommended_fixes"],
                prevention=top_issue["prevention"],
            )
        
        # PRIORITY 3: Check events for scheduling/resource issues
        event_issues = self._analyze_events(signals.events)
        if event_issues:
            event_issues.sort(key=lambda x: x["confidence"], reverse=True)
            top_issue = event_issues[0]
            return InvestigationReport(
                root_cause=top_issue["root_cause"],
                confidence=top_issue["confidence"],
                evidence=top_issue["evidence"],
                recommended_fixes=top_issue["recommended_fixes"],
                prevention=top_issue["prevention"],
            )
        
        # PRIORITY 4: Last resort: check network (service selector issues)
        network_issues = self._analyze_network(signals.network, target_pod=signals.target)
        if network_issues:
            network_issues.sort(key=lambda x: x["confidence"], reverse=True)
            top_issue = network_issues[0]
            return InvestigationReport(
                root_cause=top_issue["root_cause"],
                confidence=top_issue["confidence"],
                evidence=top_issue["evidence"],
                recommended_fixes=top_issue["recommended_fixes"],
                prevention=top_issue["prevention"],
            )
        
        # No issues found
        print(f"[DEBUG] No issues detected - returning healthy status with confidence 75%")
        return InvestigationReport(
            root_cause=f"{workload_desc} appears healthy. No critical issues detected.",
            confidence=75,
            evidence=[
                f"All {workload_desc.lower()} signals are normal.",
                "No errors in logs or events.",
                "Service endpoints healthy.",
            ],
            recommended_fixes=[
                "Continue monitoring for changes.",
                "Review application performance metrics if issue is intermittent.",
            ],
            prevention=[
                "Maintain regular health checks and alerts.",
            ],
        )

    def _analyze_pods(self, pods: list[dict]) -> list[dict]:
        """Analyze pod-level signals."""
        issues = []
        
        for pod in pods:
            name = pod.get("name", "unknown")
            phase = pod.get("phase", "").lower()
            reason = pod.get("reason", "").lower()
            restarts = pod.get("restartCount", 0)
            
            # Critical: Pod is in a bad state
            if phase == "crashloopbackoff":
                issues.append({
                    "root_cause": f"Pod '{name}' is in CrashLoopBackOff - application crashes repeatedly on startup",
                    "confidence": 89,
                    "evidence": [f"Pod phase: {phase}", f"Pod restart count: {restarts}"],
                    "recommended_fixes": [
                        f"View error logs: kubectl logs {name} --previous",
                        f"Describe pod for events: kubectl describe pod {name}",
                        "Common causes: missing env vars, config errors, dependency issues",
                        "Check if startup probe is failing",
                        "Verify all required ConfigMaps and Secrets are mounted"
                    ],
                    "prevention": ["Add liveness probes with appropriate thresholds", "Add startup probes for slow-starting apps"]
                })
            
            elif phase == "imagepullbackoff":
                issues.append({
                    "root_cause": f"Pod '{name}' cannot pull container image",
                    "confidence": 90,
                    "evidence": [f"Pod phase: ImagePullBackOff"],
                    "recommended_fixes": [
                        "Verify image name and tag are correct",
                        "Check image registry credentials",
                        "Ensure image exists in registry and is accessible",
                        f"Check event details: kubectl describe pod {name}"
                    ],
                    "prevention": ["Use image pull policy wisely", "Pre-validate images before deploy"]
                })
            
            elif phase == "pending":
                if restarts == 0:
                    issues.append({
                        "root_cause": f"Pod '{name}' cannot be scheduled (Pending) - likely resource constraints",
                        "confidence": 75,
                        "evidence": [f"Pod phase: Pending"],
                        "recommended_fixes": [
                            "Check available cluster resources: kubectl top nodes",
                            f"Describe pod for scheduling errors: kubectl describe pod {name}",
                            "Consider scaling cluster or reducing resource requests",
                            "Check node selectors and tolerations"
                        ],
                        "prevention": ["Monitor cluster capacity", "Use resource quotas"]
                    })
            
            elif phase == "unknown":
                issues.append({
                    "root_cause": f"Pod '{name}' is in Unknown state - cluster connectivity issue",
                    "confidence": 70,
                    "evidence": [f"Pod phase: Unknown"],
                    "recommended_fixes": [
                        "Check node health: kubectl describe node <node-name>",
                        "Verify cluster network connectivity",
                        "Check kubelet logs on affected node"
                    ],
                    "prevention": ["Monitor node health regularly"]
                })
            
            elif phase == "failed":
                issues.append({
                    "root_cause": f"Pod '{name}' failed to complete (phase: Failed)",
                    "confidence": 80,
                    "evidence": [f"Pod phase: Failed"],
                    "recommended_fixes": [
                        f"Check pod logs: kubectl logs {name}",
                        f"Describe pod: kubectl describe pod {name}",
                        "Check exit code: usually in pod status"
                    ],
                    "prevention": ["Use exit codes appropriately", "Add comprehensive error logging"]
                })
            
            # High restart count indicates instability
            if restarts > 3 and phase == "running":
                issues.append({
                    "root_cause": f"Pod '{name}' is restarting frequently ({restarts} restarts) - application instability",
                    "confidence": 82,
                    "evidence": [f"High restart count: {restarts}", f"Pod phase: {phase}"],
                    "recommended_fixes": [
                        f"Check recent logs: kubectl logs {name}",
                        "Look for crash patterns in logs",
                        "Check liveness probe configuration - may be too aggressive",
                        "Review resource limits - pod may be getting OOM killed silently",
                        "Check application error logs for exceptions"
                    ],
                    "prevention": ["Tune liveness/readiness probes carefully", "Add comprehensive monitoring"]
                })
        
        return issues

    def _analyze_logs(self, logs: list[dict]) -> list[dict]:
        """Analyze log signals and extract root causes from error messages."""
        issues = []
        
        # Group logs by pod to get context
        logs_by_pod = {}
        for log in logs:
            pod_name = log.get("pod_name", "unknown")
            if pod_name not in logs_by_pod:
                logs_by_pod[pod_name] = []
            logs_by_pod[pod_name].append(log)
        
        for pod_name, pod_logs in logs_by_pod.items():
            for log in pod_logs:
                message = log.get("log_snippet", "").lower()
                
                # Skip empty logs
                if not message or len(message.strip()) < 5:
                    continue
                
                # Check for connection errors (most common in cloud apps)
                if any(x in message for x in ["connection refused", "connection reset", "connection timeout", "unable to connect"]):
                    issues.append({
                        "root_cause": f"Pod '{pod_name}' cannot connect to a required service/database",
                        "confidence": 85,
                        "evidence": ["Connection error detected in logs", f"Pod: {pod_name}"],
                        "recommended_fixes": [
                            "Verify the service/database is running and accessible",
                            f"Check network policies: kubectl get networkpolicies -n <namespace>",
                            f"Verify DNS resolution: kubectl exec -it {pod_name} -- nslookup <service-name>",
                            "Check firewall rules and security groups",
                            "Verify credentials and connection string in application config"
                        ],
                        "prevention": [
                            "Add connection health checks in startup probes",
                            "Implement exponential backoff for retries",
                            "Add comprehensive error logging with context"
                        ]
                    })
                
                # Check for permission/auth errors
                if any(x in message for x in ["permission denied", "access denied", "unauthorized", "forbidden", "403", "401"]):
                    issues.append({
                        "root_cause": f"Pod '{pod_name}' has authentication/authorization issues",
                        "confidence": 88,
                        "evidence": ["Auth error detected in logs", f"Pod: {pod_name}"],
                        "recommended_fixes": [
                            "Verify service credentials and API keys are correct",
                            "Check if credentials have expired",
                            f"Verify RBAC permissions: kubectl get rolebinding,clusterrolebinding",
                            "Review access policies for external services",
                            "Check if service account has necessary permissions"
                        ],
                        "prevention": [
                            "Use managed identities or workload identity where possible",
                            "Implement credential rotation policies",
                            "Add access logs and audit trails"
                        ]
                    })
                
                # Check for database/data errors
                if any(x in message for x in ["database", "sql error", "query failed", "foreign key", "constraint violation", "table not found"]):
                    issues.append({
                        "root_cause": f"Pod '{pod_name}' has database/data access issues",
                        "confidence": 83,
                        "evidence": ["Database error detected in logs", f"Pod: {pod_name}"],
                        "recommended_fixes": [
                            "Verify database connection string is correct",
                            "Check if database server is running and accessible",
                            "Review recent database schema changes",
                            "Check database user permissions",
                            "Review database server logs for errors"
                        ],
                        "prevention": [
                            "Implement schema migration tests",
                            "Add database health checks",
                            "Monitor database availability and performance"
                        ]
                    })
                
                # Check for OOM errors
                if any(x in message for x in ["out of memory", "oom", "memory exhausted", "heap space"]):
                    issues.append({
                        "root_cause": f"Pod '{pod_name}' is running out of memory (OOM)",
                        "confidence": 92,
                        "evidence": ["OOM error detected in logs", f"Pod: {pod_name}"],
                        "recommended_fixes": [
                            "Increase memory limits in deployment spec",
                            "Profile application for memory leaks",
                            "Optimize data structures and caching",
                            "Consider pagination for large datasets",
                            "Monitor GC/garbage collection performance"
                        ],
                        "prevention": [
                            "Set appropriate memory requests and limits",
                            "Implement memory leak detection in CI/CD",
                            "Add memory usage monitoring and alerts"
                        ]
                    })
                
                # Check for dependency/library errors
                if any(x in message for x in ["module not found", "import error", "nosuchmoduleerror", "classpath", "missing dependency", "not installed"]):
                    issues.append({
                        "root_cause": f"Pod '{pod_name}' has missing dependencies or library issues",
                        "confidence": 87,
                        "evidence": ["Dependency error detected in logs", f"Pod: {pod_name}"],
                        "recommended_fixes": [
                            "Verify all required libraries are installed in container image",
                            "Check Dockerfile for missing RUN pip install / apt-get commands",
                            "Review application requirements.txt or package.json",
                            "Ensure correct versions are specified",
                            "Test image build locally before deploying"
                        ],
                        "prevention": [
                            "Use multi-stage builds to reduce image size and catch issues early",
                            "Pin dependency versions",
                            "Scan images for vulnerabilities"
                        ]
                    })
                
                # Check for general application errors/exceptions
                if any(x in message for x in ["error", "exception", "failed", "failure", "panic"]) and \
                   not any(x in message for x in ["connection", "permission", "database", "memory", "module", "not found"]):
                    issues.append({
                        "root_cause": f"Pod '{pod_name}' is experiencing application errors",
                        "confidence": 75,
                        "evidence": ["Error/exception detected in logs", f"Pod: {pod_name}"],
                        "recommended_fixes": [
                            f"Review detailed logs: kubectl logs {pod_name}",
                            f"Check previous logs: kubectl logs {pod_name} --previous",
                            "Check application configuration and environment variables",
                            "Review recent code deployments",
                            "Check for any upstream service dependencies that might be failing"
                        ],
                        "prevention": [
                            "Implement structured logging with error context",
                            "Add comprehensive error handling",
                            "Implement application monitoring and alerting"
                        ]
                    })
        
        return issues

    def _analyze_events(self, events: list[dict]) -> list[dict]:
        """Analyze Kubernetes events."""
        issues = []
        
        for event in events:
            reason = event.get("reason", "").lower()
            message = event.get("message", "").lower()
            
            if "failedscheduling" in reason:
                issues.append({
                    "root_cause": "Pod cannot be scheduled - insufficient cluster resources",
                    "confidence": 85,
                    "evidence": [f"Event: {reason}"],
                    "recommended_fixes": [
                        "Scale up node pool or cluster",
                        "Reduce resource requests",
                        "Delete unnecessary workloads"
                    ],
                    "prevention": ["Enable cluster autoscaler", "Monitor cluster capacity"]
                })
            
            if "insufficient" in message:
                issues.append({
                    "root_cause": f"Resource constraint: {message}",
                    "confidence": 82,
                    "evidence": [f"Event indicates: {message}"],
                    "recommended_fixes": [
                        "Scale cluster resources",
                        "Review resource requests"
                    ],
                    "prevention": ["Use resource quotas", "Monitor usage"]
                })
        
        return issues

    def _analyze_deployments(self, deployments: list[dict]) -> list[dict]:
        """Analyze deployment signals."""
        issues = []
        
        for dep in deployments:
            name = dep.get("name", "unknown")
            
            # Use the actual signal provider field names
            desired = dep.get("desired", 0)
            available = dep.get("available", 0)
            updated = dep.get("updated", 0)
            rollout = dep.get("rollout", "").lower()
            
            # Only report an issue if deployment is actually degraded/unhealthy
            # Healthy means: desired == available == updated AND rollout is "healthy"
            if desired == 0:
                # Skip deployments with 0 desired replicas (likely intentionally scaled down)
                continue
            
            if rollout != "healthy" or available != desired or updated != desired:
                replicas_str = f"{available}/{desired}"
                issues.append({
                    "root_cause": f"Deployment '{name}' is not ready - replicas: {replicas_str}",
                    "confidence": 77,
                    "evidence": [
                        f"Deployment status: {rollout}",
                        f"Replicas: {replicas_str}",
                        f"Updated: {updated}/{desired}"
                    ],
                    "recommended_fixes": [
                        f"Check deployment status: kubectl rollout status deployment/{name}",
                        f"View events: kubectl describe deployment {name}",
                        "Review recent deployments"
                    ],
                    "prevention": ["Use deployment strategies like RollingUpdate"]
                })
        
        return issues

    def _analyze_network(self, network: list[dict], target_pod: str | None = None) -> list[dict]:
        """Analyze network/service signals.
        
        Args:
            network: List of network signals
            target_pod: If investigating a specific pod, only check services that could affect that pod
        """
        issues = []
        
        # If investigating a specific pod, extract the service name from pod name
        # Pod names follow pattern: service-name-hash-random, we need the service part
        target_service = None
        if target_pod:
            # Extract service name from pod name (everything before the last two hash segments)
            # Example: crts-epp-intake-service-7596d95d84-zhmdr -> crts-epp-intake-service
            parts = target_pod.rsplit("-", 2)  # Split from right, keep last 2 parts
            if parts:
                target_service = parts[0].lower()
        
        for svc in network:
            service = svc.get("service", "unknown")
            endpoint_count = svc.get("endpointCount", 0)
            
            # Only report network issues if:
            # 1. We're investigating the cluster broadly (no specific target), OR
            # 2. The service name matches the target service
            # This prevents reporting unrelated service issues when investigating a specific pod
            if target_service:
                # When investigating a specific pod, only check that pod's service
                if service.lower() != target_service:
                    continue
            
            if endpoint_count == 0:
                issues.append({
                    "root_cause": f"Service '{service}' has no endpoint pods - check selector labels",
                    "confidence": 80,
                    "evidence": [f"Service endpoint count: {endpoint_count}"],
                    "recommended_fixes": [
                        f"Check service selector: kubectl get svc {service} -o yaml",
                        "Verify pod labels match selector",
                        f"View endpoints: kubectl get endpoints {service}"
                    ],
                    "prevention": ["Validate labels before deployment", "Use label validation tests"]
                })
        
        return issues

