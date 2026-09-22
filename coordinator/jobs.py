"""Reconcile a terminated Modal worker so polling cannot stay running forever."""
from datetime import datetime, timezone

from .models import RunState


TERMINAL = {"complete", "partial", "failed"}


def reconcile_job(state: RunState, store, resolve_call=None) -> RunState:
    if state.status in TERMINAL:
        return state
    call_id = store.get_job(state.run_id)
    if not call_id:
        return state
    import modal
    resolve_call = resolve_call or modal.FunctionCall.from_id
    try:
        payload = resolve_call(call_id).get(timeout=0)
    except (modal.exception.ConnectionError, modal.exception.AuthError,
            modal.exception.ServiceError, modal.exception.InternalError):
        # Failure to observe a job is not evidence that the job itself failed.
        return state
    except modal.exception.FunctionTimeoutError:
        reason = "Cloud worker exceeded its execution timeout"
    except TimeoutError:
        return state
    except Exception as exc:
        reason = f"Cloud worker terminated without a completed investigation ({type(exc).__name__})"
    else:
        try:
            result = RunState.model_validate(payload)
            if result.run_id != state.run_id or result.status not in TERMINAL:
                raise ValueError("Invalid worker result")
        except (ValueError, TypeError):
            reason = "Cloud worker returned an invalid investigation result"
        else:
            store.save(result)
            return result
    # A final snapshot may have arrived while we checked the cloud call.
    latest = store.get(state.run_id)
    if latest.status in TERMINAL:
        return latest
    latest.status, latest.stage, latest.error = "failed", "worker_failed", reason
    latest.events.append({"stage": "worker_failed", "at": datetime.now(timezone.utc).isoformat(), "error": reason})
    store.save(latest)
    return latest
