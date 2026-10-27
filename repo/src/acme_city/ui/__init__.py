"""The server-rendered ACME City demonstration interface.

The package holds the eight required screens, the shared responsibility,
evidence and history components, and the explicit scoped actions.  The
interface never decides anything: it renders what the domain services
recorded and it names the destination of every action.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04, GOV-04, EDIT-01, EDIT-02, EDIT-03
# The interface renders the resolved responsibility, the current, submitted,
# proposed and issued values, the permitted actions with their reasons, and the
# evidence and history of every governed record.

from __future__ import annotations

__all__: list[str] = []
