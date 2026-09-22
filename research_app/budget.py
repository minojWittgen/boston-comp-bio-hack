"""A persistent, non-renewing allowance for public live investigation starts."""
from uuid import uuid4
from datetime import datetime, timezone


class RunLimitError(ValueError):
    pass


class PublicRunBudget:
    def __init__(self, slots, limit=12, expires_at=None, clock=None):
        if not isinstance(limit, int) or not 0 <= limit <= 1000:
            raise ValueError("Public run limit must be an integer from 0 to 1000")
        self.slots, self.limit = slots, limit
        if expires_at is not None and expires_at.tzinfo is None:
            raise ValueError("The public allowance deadline must include a timezone")
        self.expires_at = expires_at
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def check_deadline(self):
        if self.expires_at is not None and self.clock() >= self.expires_at:
            self.exhausted()

    def exhausted(self):
        raise RunLimitError("The public demo's live allowance is used up or its trial window has ended. Tutorials still work. The host can extend the allowance, or you can deploy your own MCP server.")

    def check(self):
        # This check avoids paid visitor planning when the allowance is already used.
        # reserve() remains authoritative when requests arrive concurrently.
        self.check_deadline()
        for index in range(self.limit):
            if self.slots.get(f"live:{index}") is None:
                return
        self.exhausted()

    def reserve(self):
        self.check_deadline()
        for index in range(self.limit):
            # Modal performs this conditional put atomically across containers.
            if self.slots.put(f"live:{index}", uuid4().hex, skip_if_exists=True):
                return
        self.exhausted()
