"""Workflow runner — minimal executor for the DAG stub.

Runs nodes sequentially via edges; switch nodes branch on string match;
approval nodes pause via human_checkpoint (if available) or skip when
NALLY_HARNESS_VERIFY is false. Tool nodes call registry.execute_result.

This proves the interface; Phase 6 adds durable checkpoint store, cron, webhook.
"""

from typing import Any, Dict

from ..utils.logger import logger
from .models import Workflow


def run_workflow(workflow: Workflow, inputs: Dict[str, Any] = None, session_id: str = "workflow:default") -> Dict[str, Any]:
    """Run a workflow DAG, return {outputs, status, errors}."""
    inputs = inputs or {}
    errors = workflow.validate()
    if errors:
        return {"status": "invalid", "errors": errors, "outputs": {}}

    outputs: Dict[str, Any] = {}
    # Build id -> node map
    nodes = {n.id: n for n in workflow.nodes}
    # Build adjacency from nodes[].next and edges[]
    adj: Dict[str, list] = {nid: [] for nid in nodes}
    for n in workflow.nodes:
        for nxt in n.next:
            if nxt in nodes:
                adj[n.id].append(nxt)
    for e in workflow.edges:
        if e.from_id in adj and e.to_id not in adj[e.from_id]:
            adj[e.from_id].append(e.to_id)

    # Find start: node with no incoming
    incoming = {e.to_id for e in workflow.edges}
    for n in workflow.nodes:
        for nxt in n.next:
            incoming.add(nxt)
    start_ids = [nid for nid in nodes if nid not in incoming]
    if not start_ids:
        start_ids = [workflow.nodes[0].id] if workflow.nodes else []

    # Simple BFS with visited to avoid loops (cap 20 steps)
    visited = set()
    queue = list(start_ids)
    steps = 0
    while queue and steps < 20:
        nid = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        steps += 1
        node = nodes.get(nid)
        if not node:
            continue

        try:
            if node.kind == "approval":
                # Human checkpoint — if harness disabled, auto-approve
                try:
                    from ..config import NALLY_HARNESS_VERIFY

                    if not NALLY_HARNESS_VERIFY:
                        outputs[nid] = "auto-approved (harness verify off)"
                    else:
                        # In real run, this would pause and await POST /api/approve
                        outputs[nid] = f"approval required: {node.message or nid}"
                        logger.info(f"Workflow approval node {nid} — would pause for human")
                except Exception:
                    outputs[nid] = "approval skipped"

            elif node.kind == "switch":
                # Branch on prior output string match
                prev_val = ""
                # Find most recent output to switch on
                for k in reversed(list(outputs.keys())):
                    prev_val = str(outputs[k])
                    break
                # Also allow explicit input key
                if not prev_val and inputs:
                    prev_val = str(list(inputs.values())[0])
                target = None
                if node.cases:
                    for key, dest in node.cases.items():
                        if key.lower() in prev_val.lower():
                            target = dest
                            break
                if not target:
                    target = node.default
                if target and target in nodes and target not in visited and target not in queue:
                    # Prioritize target: put front
                    queue.insert(0, target)
                continue  # switch doesn't produce output, just branches

            elif node.kind == "tool" and node.tool:
                from ..tools.registry import registry

                # Simple template: {{input}} or {{node.output}}
                raw_in = node.input or inputs.get("input", "")
                # Resolve {{key}} placeholders from outputs/inputs
                import re

                def _repl(m):
                    key = m.group(1).strip()
                    # support {{node.output}} or {{input}}
                    if "." in key:
                        base, attr = key.split(".", 1)
                        if base in outputs:
                            val = outputs[base]
                            if isinstance(val, dict) and attr in val:
                                return str(val[attr])
                            return str(val)
                    return str(outputs.get(key, inputs.get(key, "")))

                resolved = re.sub(r"\{\{([^}]+)\}\}", _repl, raw_in)
                tr = registry.execute_result(node.tool, {"query": resolved} if node.tool in ("web_search", "fetch") else {"input": resolved})
                outputs[nid] = tr.to_llm_text()[:2000]

            elif node.kind == "agent":
                # Delegate to NallyAgent via session_manager (same brain)
                try:
                    from ..agent.sessions import session_manager

                    prompt = node.prompt or ""
                    # Template resolve
                    import re

                    def _repl2(m):
                        key = m.group(1).strip()
                        if "." in key:
                            base, attr = key.split(".", 1)
                            if base in outputs:
                                val = outputs[base]
                                if isinstance(val, dict) and attr in val:
                                    return str(val[attr])
                                return str(val)
                        return str(outputs.get(key, inputs.get(key, "")))

                    resolved = re.sub(r"\{\{([^}]+)\}\}", _repl2, prompt) if prompt else str(inputs.get("input", ""))

                    def _sync():
                        return session_manager.process(session_id, resolved)

                    import asyncio

                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            import concurrent.futures

                            with concurrent.futures.ThreadPoolExecutor() as ex:
                                fut = ex.submit(session_manager.process, session_id, resolved)
                                outputs[nid] = fut.result(timeout=30)
                        else:
                            outputs[nid] = loop.run_until_complete(_sync()) if asyncio.iscoroutinefunction(_sync) else session_manager.process(session_id, resolved)
                    except Exception:
                        outputs[nid] = session_manager.process(session_id, resolved)
                except Exception as e:
                    outputs[nid] = f"agent error: {e}"

            else:
                outputs[nid] = f"unknown kind {node.kind}"

            # Enqueue next nodes
            for nxt in adj.get(nid, []):
                if nxt not in visited and nxt not in queue:
                    queue.append(nxt)

        except Exception as e:
            logger.warning(f"Workflow node {nid} failed: {e}")
            outputs[nid] = f"error: {e}"

    return {"status": "ok", "outputs": outputs, "visited": list(visited)}
