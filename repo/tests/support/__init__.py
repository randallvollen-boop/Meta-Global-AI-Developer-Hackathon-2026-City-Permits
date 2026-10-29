"""Shared test support: the HTTP client helpers and the navigation expectations.

A test module puts ``tests`` on ``sys.path`` and imports ``support.client`` or
``support.nav_expectations``, so no lane copies these helpers again.  The
``schema_groups_<lane>.py`` files beside this package are read by path from
``tests/unit/test_schema.py``.
"""
