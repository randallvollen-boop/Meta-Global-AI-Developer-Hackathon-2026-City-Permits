"""Pure, side-effect-free evaluation kernels shared by production and simulation.

Everything in this package takes frozen facts, documents and configuration and
returns plain values.  Nothing here reads the database, adds a finding, changes
a status, writes a file or calls a provider.  The intake and adjudication
agents call these same functions in production, and the what-if policy
simulation calls them over frozen case inputs, so both paths always agree.
"""
