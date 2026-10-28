"""What-if policy evaluation: pure kernels over frozen case inputs.

This package re-scores frozen case inputs under a frozen baseline configuration
and under an in-memory scenario copy of it, and reports the difference.  It
never reads or writes the database while it runs (``baseline.py`` and
``loader.py`` are the only modules that read, and they only read), never calls
a provider and never changes a rule, a fee, a type or an application.

Layout:

* ``config``      the frozen baseline configuration and its hash;
* ``changes``     the typed scenario changes and the in-memory scenario copy;
* ``population``  the frozen case inputs a population generator feeds in;
* ``kernel``      one case, scored under one configuration;
* ``fees``        the fee kernel (hypothetical assessed fees);
* ``impact``      baseline versus scenario for every case.
"""

#: The version of the evaluation engine.  It is part of every result hash, so a
#: result made by a different engine never compares equal to this one.
ENGINE_VERSION = "policy-kernel-1"
