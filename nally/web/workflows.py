"""Workflow webhook endpoints — trigger, resume, list runs.

- POST /workflows/trigger/{name}       Trigger a named workflow from workflows/*.yaml|json
- POST /workflows/run/{id}/resume      Resume a paused run (approval node completed)
- GET  /workflows/runs                 List recent runs (status, updated, id)

All endpoints require Bearer NALLY_INTERNAL_TOKEN when set.
"""

import json
import os
import threading
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

_INTERNAL_TOKEN = os.getenv("NALLY_INTERNAL_TOKEN", "")


def _check_auth(request: Request):
    """Return None if valid, else JSONResponse 401."""
    if not _INTERNAL_TOKEN:
        return None
    auth = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip() if auth.lower().startswith("bearer ") else ""
    if token != _INTERNAL_TOKEN:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


def _load_workflow_by_name(name: str):
    """Find workflow definition by name in workflows/*.yaml|json."""
    from nally.config import NALLY_WORKFLOWS_DIR

    wf_dir = Path(NALLY_WORKFLOWS_DIR)
    if not wf_dir.exists():
        return None, f"workflows dir not found: {wf_dir}"

    for ext in ("*.yaml", "*.yml", "*.json"):
        for p in wf_dir.glob(ext):
            try:
                if p.suffix in (".yaml", ".yml"):
                    import yaml
                    data = yaml.safe_load(p.read_text(encoding="utf-8"))
                else:
                    data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("name") == name:
                    return data, None
            except Exception:
                continue
    return None, f"workflow '{name}' not found in {wf_dir}"


@router.post("/workflows/trigger/{name}")
async def trigger_workflow(name: str, request: Request):
    """Trigger a named workflow by definition name.

    Body (optional): {"input": "...", "session_id": "..."}
    Runs async in threadpool — returns run_id immediately.
    """
    auth_err = _check_auth(request)
    if auth_err:
        return auth_err

    data, err = _load_workflow_by_name(name)
    if err:
        return JSONResponse({"error": err}, status_code=404)

    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        body = {}

    inputs = body.get("input") or body.get("inputs") or {}
    session_id = body.get("session_id") or f"workflow:webhook:{name}"

    try:
        from ..workflows.models import Workflow
        from ..workflows.runner import run_workflow
        from ..workflows.store import workflow_store

        wf = Workflow.from_dict(data)
        run_id = workflow_store.new_id()

        def _run():
            try:
                res = run_workflow(wf, inputs=inputs, session_id=session_id, run_id=run_id)
                from ..utils.logger import logger
                logger.info(f"Workflow {name} trigger completed: {res.get('status')} run={run_id}")
            except Exception as e:
                from ..utils.logger import logger
                logger.warning(f"Workflow {name} trigger failed: {e}")

        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "accepted", "run_id": run_id, "workflow": name})
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=500)


@router.post("/workflows/run/{run_id}/resume")
async def resume_workflow(run_id: str, request: Request):
    """Resume a paused workflow run.

    Body (optional): {"approval_output": "..."}
    """
    auth_err = _check_auth(request)
    if auth_err:
        return auth_err

    try:
        from ..workflows.store import workflow_store

        chk = workflow_store.get(run_id)
        if not chk:
            return JSONResponse({"error": f"run {run_id} not found"}, status_code=404)
        if chk["status"] != "paused":
            return JSONResponse({"error": f"run status is '{chk['status']}', not paused"}, status_code=409)

        try:
            body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        except Exception:
            body = {}

        approval_output = body.get("approval_output", "approved")

        # Update outputs with approval node value and mark visited
        outputs = chk["outputs"]
        visited = chk["visited"]
        approval_node = None

        # Find the approval node — last visited node that produced "approval required:"
        for nid in reversed(visited):
            val = str(outputs.get(nid, ""))
            if "approval required:" in val or "approval required:" in val:
                approval_node = nid
                break

        if not approval_node:
            return JSONResponse({"error": "no approval node found in run"}, status_code=409)

        outputs[approval_node] = approval_output

        # Find the workflow definition by name
        wf_data, err = _load_workflow_by_name(chk["workflow_name"])
        if err:
            return JSONResponse({"error": f"workflow definition missing: {err}"}, status_code=500)

        from ..workflows.models import Workflow
        from ..workflows.runner import run_workflow

        wf = Workflow.from_dict(wf_data)

        def _resume():
            try:
                res = run_workflow(wf, inputs=chk["inputs"], session_id=f"workflow:resume:{run_id}", run_id=run_id)
                from ..utils.logger import logger
                logger.info(f"Workflow {chk['workflow_name']} resume completed: {res.get('status')} run={run_id}")
            except Exception as e:
                from ..utils.logger import logger
                logger.warning(f"Workflow {chk['workflow_name']} resume failed: {e}")

        threading.Thread(target=_resume, daemon=True).start()
        return JSONResponse({"status": "accepted", "run_id": run_id, "approval": approval_output})
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=500)


@router.get("/workflows/runs")
async def list_runs(request: Request, limit: int = 20):
    """List recent workflow runs. No auth required (read-only)."""
    try:
        from ..workflows.store import workflow_store

        runs = workflow_store.list_recent(limit=min(limit, 100))
        return JSONResponse({"runs": runs, "count": len(runs)})
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)
