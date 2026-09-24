"""ParkIQ — config-driven site selection and underwriting for paid surface parking lots.

The analytical core never imports ``arcpy`` (docs/ENGINEERING.md); ArcGIS integration lives in
``toolbox/`` and ``arcgis/``.
"""

from __future__ import annotations

__version__ = "0.1.0"


def _use_os_trust_store() -> None:
    """Verify HTTPS against the operating-system certificate store (not just certifi).

    Needed on networks that inspect TLS with an organisation root certificate. Certificate
    verification stays on; only the trust anchors change. No-op if the optional ``truststore``
    package is absent.
    """
    try:
        import truststore
    except ImportError:
        return
    truststore.inject_into_ssl()


_use_os_trust_store()
