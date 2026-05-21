from mcp.server.transport_security import TransportSecurityMiddleware

_orig_init = TransportSecurityMiddleware.__init__


def _patched_init(self, settings=None):
    _orig_init(self, settings)
    self.settings.enable_dns_rebinding_protection = False


TransportSecurityMiddleware.__init__ = _patched_init

from app.database import init_db  # noqa: E402
from app.identity import init_identity  # noqa: E402
from app.mcp_server import mcp  # noqa: E402
from app.signing import init_protocol  # noqa: E402

init_db()
init_identity()
init_protocol()

app = mcp.streamable_http_app()
