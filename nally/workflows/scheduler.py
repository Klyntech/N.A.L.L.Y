"""Workflow scheduler — cron triggers for durable workflows.

Free-tier friendly: uses threading + simple cron check (no APScheduler dep).
Reads workflows/*.yaml or workflows/*.json with optional `cron: "*/5 * * * *"` field.
When due, enqueues run_workflow via threadpool (non-blocking).

Env:
  NALLY_WORKFLOW_CRON_ENABLED=false  (default off, opt-in)
  NALLY_WORKFLOW_CRON_INTERVAL=60    (seconds between checks)

Cron parsing: supports 5-field "* * * * *" (minute hour dom month dow) via croniter if installed,
otherwise simple "* * * * *" and "*/n * * * *" only.

On Render Free, cron sleeps when instance sleeps — durable runs will resume on wake via checkpoint store.
"""

import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger("nally.workflows.scheduler")

_cron_enabled = os.getenv("NALLY_WORKFLOW_CRON_ENABLED", "false").lower() == "true"
_cron_interval = int(os.getenv("NALLY_WORKFLOW_CRON_INTERVAL", "60"))

# In-memory last-run tracking: workflow_name -> last_run_epoch
_last_run: dict = {}
_thread: threading.Thread | None = None
_stop = threading.Event()


def _should_run_now(cron_expr: str, now: float) -> bool:
    """Check if cron is due. Supports '* * * * *' and '*/n * * * *' via simple logic, else via croniter."""
    cron_expr = (cron_expr or "").strip()
    if not cron_expr or cron_expr == "":
        return False
    # Try croniter if available (more accurate)
    try:
        from croniter import croniter

        base = now - 60  # look back 60s window
        itr = croniter(cron_expr, time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(base)))
        nxt = itr.get_next(float)
        # Due if next occurrence is within last interval + 5s grace
        return abs(nxt - now) < (_cron_interval + 5)
    except ImportError:
        pass
    except Exception:
        pass

    # Simple fallback: only "*/n * * * *" and "* * * * *"
    parts = cron_expr.split()
    if len(parts) != 5:
        return False
    minute_field = parts[0]
    # Get current minute
    lt = time.gmtime(now)
    minute = lt.tm_min
    if minute_field == "*":
        # Every minute — check if we haven't run this minute
        return True
    if minute_field.startswith("*/"):
        try:
            n = int(minute_field[2:])
            return minute % n == 0
        except Exception:
            return False
    try:
        # Single minute number
        return int(minute_field) == minute
    except Exception:
        return False


def _load_workflows_with_cron():
    """Find workflows/*.yaml or *.json with cron field."""
    base = Path(__file__).parent
    # Also check repo root workflows/ if running from different cwd
    candidates = []
    for ext in ("*.yaml", "*.yml", "*.json"):
        candidates.extend(base.glob(ext))
        candidates.extend((Path.cwd() / "workflows").glob(ext))
        candidates.extend((Path.cwd() / "nally" / "workflows").glob(ext))
    out = []
    for p in candidates:
        try:
            if p.suffix in (".yaml", ".yml"):
                try:
                    import yaml
                except ImportError:
                    continue
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
            else:
                import json

                data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("cron"):
                out.append((p, data))
        except Exception as e:
            logger.debug(f"cron load failed {p}: {e}")
    return out


def _trigger_workflow(data: dict, source: str):
    name = data.get("name", "workflow")
    logger.info(f"Cron trigger {name} from {source}")
    try:
        from .models import Workflow
        from .runner import run_workflow

        wf = Workflow.from_dict(data)
        # Run in threadpool (non-blocking, same as webhook)
        def _run():
            try:
                res = run_workflow(wf, inputs={"trigger": "cron", "cron": data.get("cron")}, session_id=f"workflow:cron:{name}")
                logger.info(f"Cron {name} completed: {res.get('status')} visited {res.get('visited')}")
            except Exception as e:
                logger.warning(f"Cron {name} failed: {e}")

        threading.Thread(target=_run, daemon=True).start()
    except Exception as e:
        logger.warning(f"Cron trigger failed for {name}: {e}")


def _loop():
    logger.info(f"Workflow cron scheduler started (interval {_cron_interval}s, enabled {_cron_enabled})")
    while not _stop.is_set():
        try:
            if _cron_enabled:
                now = time.time()
                for p, data in _load_workflows_with_cron():
                    cron = data.get("cron", "")
                    name = data.get("name", str(p))
                    last = _last_run.get(name, 0)
                    # Avoid double-trigger within interval
                    if now - last < _cron_interval - 5:
                        continue
                    if _should_run_now(cron, now):
                        _last_run[name] = now
                        _trigger_workflow(data, str(p))
        except Exception as e:
            logger.debug(f"cron loop error: {e}")
        _stop.wait(_cron_interval)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="workflow-cron")
    _thread.start()
    logger.info("Workflow scheduler thread started")


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=2)


# Auto-start when imported if enabled (called from lifespan)
if _cron_enabled:
    # Don't auto-start at import time in tests — wait for explicit start() from web lifespan
    pass
