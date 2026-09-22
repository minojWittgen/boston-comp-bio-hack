"""Request-scoped model access. Credentials never enter jobs or research state."""
from dataclasses import dataclass
import re

from pydantic import SecretStr

from coordinator.engine import Coordinator
from coordinator.planner import ClaudePlanner, ExplicitPlanner, PlanningError
from coordinator.runtime import build_coordinator


class ModelSetupError(ValueError):
    """A safe, user-facing model configuration or provider error."""


@dataclass(frozen=True)
class PlanningCredentials:
    api_key: SecretStr
    model: str

    @classmethod
    def from_headers(cls, headers):
        key = headers.get("x-anthropic-api-key", "").strip()
        model = headers.get("x-anthropic-model", "").strip()
        if not key or not model:
            raise ModelSetupError("Add your Anthropic API key and model ID in Model settings. There is no shared model key.")
        if len(key) > 512 or any(not 33 <= ord(c) <= 126 for c in key):
            raise ModelSetupError("The API key format is invalid. Check Model settings.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", model):
            raise ModelSetupError("The model ID format is invalid. Check Model settings.")
        return cls(SecretStr(key), model)


def plan_with_credentials(request, credentials):
    if credentials is None:
        raise ModelSetupError("Add your Anthropic API key and model ID in Model settings. There is no shared model key.")
    from anthropic import Anthropic, AuthenticationError, RateLimitError, NotFoundError, PermissionDeniedError, APITimeoutError
    try:
        # Explicit client injection bypasses every shared-key/model environment fallback.
        # Keep the destination fixed: a deployment URL override must not receive visitor keys.
        with Anthropic(api_key=credentials.api_key.get_secret_value(), auth_token=None,
                       base_url="https://api.anthropic.com", max_retries=0, timeout=60.0) as client:
            return ClaudePlanner(model=credentials.model, client=client).plan(request)
    except AuthenticationError:
        raise ModelSetupError("Anthropic rejected your API key. Check Model settings.") from None
    except NotFoundError:
        raise ModelSetupError("Anthropic could not find or grant access to that model. Use an exact model ID available to your API account.") from None
    except PermissionDeniedError:
        raise ModelSetupError("Your Anthropic key does not have permission to use this model. Check its account and workspace permissions.") from None
    except RateLimitError:
        raise ModelSetupError("Your Anthropic account reached a rate or usage limit. Check your account and try later.") from None
    except APITimeoutError:
        raise ModelSetupError("Anthropic did not finish planning within 60 seconds. No investigation was started. Try a narrower question.") from None
    except PlanningError:
        raise  # Canonical planner messages contain no provider response bodies.
    except Exception:
        raise ModelSetupError("Could not create a plan with your Anthropic account. Check the model ID, credits and connection.") from None


class PreparedPlanner:
    """Carry an already validated intent plan into the unchanged research engine."""
    def __init__(self, request, plan):
        self.request, self.prepared = request, plan

    def plan(self, request):
        if request != self.request:
            raise ValueError("Prepared plan does not match the research request")
        return self.prepared.model_copy(deep=True)


def public_coordinator(store=None):
    engine = build_coordinator(store)
    engine.planner = ExplicitPlanner()
    return engine


def with_prepared_plan(engine, request, plan):
    return Coordinator(PreparedPlanner(request, plan), engine.provider, engine.store,
                       budget_seconds=engine.budget_seconds)
