"""The base exception for the whole package.

Lives in the domain so every layer can raise and catch a common type without
reaching outward. Concrete failures that belong to persistence or wiring live
in `application.errors`; a refusal is NOT an error and lives in
`domain.outcomes`.
"""

from __future__ import annotations


class TktError(Exception):
    """Base class for every exception tkt-store raises."""
