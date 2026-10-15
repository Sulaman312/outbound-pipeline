"""Exceptions shared across the pipeline."""


class PipelineError(Exception):
    """Base class for every error the pipeline raises on purpose."""


class ConfigError(PipelineError):
    """A config file is missing, malformed, or refers to something unknown."""


class MissingSecretError(ConfigError):
    """An API key the run needs is not set in the environment."""


class BudgetExceededError(PipelineError):
    """A provider's monthly cap would be crossed by the next request."""


class ProviderError(PipelineError):
    """A provider API returned an error we cannot recover from by retrying."""

    def __init__(self, provider: str, status: int, body: str):
        super().__init__(f"{provider} returned HTTP {status}: {body[:300]}")
        self.provider = provider
        self.status = status
        self.body = body
