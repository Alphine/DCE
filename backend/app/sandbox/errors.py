"""Exceptions raised inside the sandbox package."""


class SandboxError(Exception):
    """Base class for sandbox failures."""


class SandboxConfigError(SandboxError):
    """Runner misconfigured, or refused by policy (for example the local runner in production)."""


class SandboxInputError(SandboxError, ValueError):
    """Script or inputs failed validation before anything was created."""


class SandboxSecurityError(SandboxError):
    """docker inspect did not confirm the required security configuration. The container is never started."""


class ArtifactRejected(SandboxError, ValueError):
    """An output file failed name, type, or size validation (SDD 17.2, 17.4)."""
