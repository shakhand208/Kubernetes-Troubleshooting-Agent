from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict

from app.core.models import (
    InvestigationCreateResponse,
    InvestigationEvent,
    InvestigationProgress,
    InvestigationRequest,
    InvestigationState,
    SignalBundle,
    utc_now_iso,
)
from app.services.ai_agent import AIAgent
from app.services.history_store import HistoryStore
from app.services.signal_provider import SignalProvider


class InvestigationService:
    def __init__(
        self,
        signal_provider: SignalProvider,
        ai_agent: AIAgent,
        history_store: HistoryStore,
        kubeconfig: str | None = None,
    ) -> None:
        self._signal_provider = signal_provider
        self._ai_agent = ai_agent
        self._history_store = history_store
        self._kubeconfig = kubeconfig
        self._investigations: dict[str, InvestigationState] = {}
        self._subscribers: dict[str, list[asyncio.Queue[dict]]] = defaultdict(list)

    async def start_investigation(
        self, request: InvestigationRequest
    ) -> InvestigationCreateResponse:
        inv_id = str(uuid.uuid4())
        state = InvestigationState(id=inv_id, request=request, status="pending")
        self._investigations[inv_id] = state

        self._emit(
            inv_id,
            InvestigationEvent(
                investigation_id=inv_id,
                status="pending",
                progress=InvestigationProgress(
                    step="queued",
                    detail="Investigation queued",
                ),
            ),
        )

        asyncio.create_task(self._run_investigation(inv_id))
        return InvestigationCreateResponse(
            id=inv_id,
            status="pending",
            message="Investigation started",
        )

    def list_investigations(self) -> list[InvestigationState]:
        return sorted(
            self._investigations.values(),
            key=lambda s: s.created_at,
            reverse=True,
        )

    def get_investigation(self, inv_id: str) -> InvestigationState | None:
        return self._investigations.get(inv_id)

    async def subscribe(self, inv_id: str) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        self._subscribers[inv_id].append(queue)
        return queue

    def unsubscribe(self, inv_id: str, queue: asyncio.Queue[dict]) -> None:
        listeners = self._subscribers.get(inv_id, [])
        if queue in listeners:
            listeners.remove(queue)

    async def _run_investigation(self, inv_id: str) -> None:
        state = self._investigations[inv_id]
        state.status = "running"
        state.updated_at = utc_now_iso()

        self._progress(inv_id, "starting", "Initializing investigation workflow")

        signals = SignalBundle()
        signals.target = state.request.target  # Set the target for analysis filtering

        try:
            self._progress(inv_id, "pods", "Checking pod health")
            signals.pods = await self._signal_provider.get_pod_signals(state.request)

            self._progress(inv_id, "logs", "Collecting container logs")
            signals.logs = await self._signal_provider.get_log_signals(state.request)

            self._progress(inv_id, "events", "Analyzing Kubernetes events")
            signals.events = await self._signal_provider.get_event_signals(state.request)

            # Collect workload-type-specific signals
            workload_type = state.request.workload_type
            if workload_type == "pods":
                self._progress(inv_id, "deployments", "Analyzing pod signals")
                signals.deployments = await self._signal_provider.get_deployment_signals(state.request)
            elif workload_type == "statefulsets":
                self._progress(inv_id, "deployments", "Analyzing StatefulSet rollout status")
                signals.deployments = await self._signal_provider.get_statefulset_signals(state.request)
            elif workload_type == "daemonsets":
                self._progress(inv_id, "deployments", "Analyzing DaemonSet status")
                signals.deployments = await self._signal_provider.get_daemonset_signals(state.request)
            elif workload_type == "jobs":
                self._progress(inv_id, "deployments", "Analyzing Job completion status")
                signals.deployments = await self._signal_provider.get_job_signals(state.request)
            else:
                # Default: Get all types
                self._progress(inv_id, "deployments", "Inspecting deployment rollout health")
                signals.deployments = await self._signal_provider.get_deployment_signals(state.request)

            self._progress(inv_id, "network", "Validating service selectors and networking")
            signals.network = await self._signal_provider.get_network_signals(state.request)

            self._progress(inv_id, "reasoning", "Correlating evidence and identifying root cause")
            state.report = await self._ai_agent.analyze(signals)

            state.status = "completed"
            state.updated_at = utc_now_iso()
            self._history_store.append(state)

            self._emit(
                inv_id,
                InvestigationEvent(
                    investigation_id=inv_id,
                    status=state.status,
                    report=state.report,
                    updated_at=state.updated_at,
                ),
            )
        except Exception as exc:
            state.status = "failed"
            state.error = str(exc)
            state.updated_at = utc_now_iso()
            self._emit(
                inv_id,
                InvestigationEvent(
                    investigation_id=inv_id,
                    status=state.status,
                    error=state.error,
                    updated_at=state.updated_at,
                ),
            )

    def _progress(self, inv_id: str, step: str, detail: str) -> None:
        state = self._investigations[inv_id]
        progress = InvestigationProgress(step=step, detail=detail)
        state.progress.append(progress)
        state.updated_at = utc_now_iso()
        self._emit(
            inv_id,
            InvestigationEvent(
                investigation_id=inv_id,
                status=state.status,
                progress=progress,
                updated_at=state.updated_at,
            ),
        )

    def _emit(self, inv_id: str, event: InvestigationEvent) -> None:
        payload = event.model_dump()
        for queue in list(self._subscribers.get(inv_id, [])):
            queue.put_nowait(payload)
