"""The lane seed modules that register reset hooks.

:func:`acme_city.fixtures.reset.reset_demo` imports this module before it runs
the registered hooks.  Each import below registers that lane's hooks with
:func:`acme_city.fixtures.reset.register_seed`; a lane adds its seed data in its
own module, never in ``reset.py`` or here.
"""

from acme_city.agents import seed as agents_seed  # noqa: F401  (operator lane)
from acme_city.registry import automation_seed  # noqa: F401  (autolink lane)
