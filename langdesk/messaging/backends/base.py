class SMSError(Exception):
    """Raised when a provider refuses or fails to send a message."""


class BaseSMSBackend:
    name = "base"

    def send(self, to: str, body: str) -> str:
        raise NotImplementedError
