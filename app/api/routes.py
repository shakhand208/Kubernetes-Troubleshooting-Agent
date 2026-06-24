from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.core.models import InvestigationRequest, InvestigationState
from app.core.service_state import (
    get_investigation_service,
    set_current_service,
    get_current_signal_provider,
    set_current_signal_provider,
)
from app.services.azure_cli_auth import AzureCliAuthManager
from app.services.investigation_service import InvestigationService
from app.services.kubernetes_signal_provider import RealKubernetesSignalProvider

router = APIRouter(prefix="/api", tags=["investigations"])


@router.get("/auth/status")
def get_auth_status():
    """Check if user is authenticated with Azure CLI."""
    auth = AzureCliAuthManager()
    is_auth = auth.is_authenticated()
    account = auth.get_current_account() if is_auth else None
    print(f"[DEBUG] Auth status - authenticated: {is_auth}, account: {account}")
    return {
        "authenticated": is_auth,
        "account": account,
    }


@router.get("/clusters")
def list_clusters():
    """List all AKS clusters in current subscription."""
    auth = AzureCliAuthManager()
    if not auth.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Azure CLI. Run 'az login' first.")
    
    clusters = auth.list_aks_clusters()
    return {"clusters": clusters}


@router.post("/clusters/{cluster_name}/connect")
def connect_to_cluster(
    cluster_name: str,
    resource_group: str = Query(...),
):
    """Connect to a specific AKS cluster."""
    auth = AzureCliAuthManager()
    if not auth.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Azure CLI. Run 'az login' first.")

    try:
        creds = auth.get_cluster_credentials(resource_group, cluster_name)
        if not creds or "kubeconfig" not in creds:
            raise HTTPException(status_code=500, detail="Failed to get cluster credentials")

        kubeconfig = creds["kubeconfig"]
        signal_provider = RealKubernetesSignalProvider(kubeconfig)
        from app.services.ai_agent import AIAgent
        from app.services.history_store import HistoryStore

        _history_path = "data/investigation_history.json"
        real_service = InvestigationService(
            signal_provider=signal_provider,
            ai_agent=AIAgent(),
            history_store=HistoryStore(_history_path),
            kubeconfig=kubeconfig,
        )
        set_current_service(real_service)
        set_current_signal_provider(signal_provider)
        return {"status": "connected", "cluster_name": cluster_name}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to connect to cluster: {str(exc)}")


@router.post("/investigations")
async def create_investigation(
    request: InvestigationRequest,
    service: InvestigationService = Depends(get_investigation_service),
):
    print(f"\n{'='*60}")
    print(f"[DEBUG] CREATE INVESTIGATION REQUEST")
    print(f"{'='*60}")
    print(f"incident_name: {request.incident_name}")
    print(f"namespace: {request.namespace}")
    print(f"target: {request.target}")
    print(f"workload_type: {request.workload_type}")
    print(f"{'='*60}\n")
    
    return await service.start_investigation(request)


@router.get("/investigations", response_model=list[InvestigationState])
def list_investigations(
    service: InvestigationService = Depends(get_investigation_service),
):
    return service.list_investigations()


@router.get("/investigations/{investigation_id}", response_model=InvestigationState)
def get_investigation(
    investigation_id: str,
    service: InvestigationService = Depends(get_investigation_service),
):
    state = service.get_investigation(investigation_id)
    if not state:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return state


@router.websocket("/investigations/{investigation_id}/stream")
async def stream_investigation(
    websocket: WebSocket,
    investigation_id: str,
    service: InvestigationService = Depends(get_investigation_service),
):
    state = service.get_investigation(investigation_id)
    if not state:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    await websocket.send_json(
        {
            "investigation_id": investigation_id,
            "status": state.status,
            "progress": state.progress[-1].model_dump() if state.progress else None,
            "report": state.report.model_dump() if state.report else None,
            "error": state.error,
            "updated_at": state.updated_at,
        }
    )

    if state.status in {"completed", "failed"}:
        await websocket.close()
        return

    queue = await service.subscribe(investigation_id)

    try:

        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event.get("status") in {"completed", "failed"}:
                break
    except WebSocketDisconnect:
        pass
    finally:
        service.unsubscribe(investigation_id, queue)


@router.get("/namespaces")
async def get_namespaces():
    """Get all namespaces in the connected cluster."""
    signal_provider = get_current_signal_provider()
    if not signal_provider:
        raise HTTPException(status_code=400, detail="No cluster connected")
    
    try:
        namespaces = await signal_provider.get_namespaces()
        return {"namespaces": namespaces}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to get namespaces: {str(exc)}")


@router.get("/namespaces/{namespace}/workloads")
async def get_namespace_workloads(namespace: str):
    """Get all workloads in a specific namespace."""
    signal_provider = get_current_signal_provider()
    if not signal_provider:
        raise HTTPException(status_code=400, detail="No cluster connected")
    
    try:
        workloads = await signal_provider.get_workloads(namespace)
        return workloads
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to get workloads: {str(exc)}")
