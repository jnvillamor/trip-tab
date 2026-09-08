class ApplicationError(Exception):
  """Base class for application-level exceptions."""

class NotFoundError(ApplicationError):
  """Raised when a requested resource is not found."""

class NotAuthorizedError(ApplicationError):
  """Raised when a user is not authorized to perform an action."""
