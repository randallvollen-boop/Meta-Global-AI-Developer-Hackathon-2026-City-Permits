"""The permit workflow.

An application, its immutable submitted revisions, its evaluations, its
reviewer decisions and its issued permit are separate records.  Approval and
issuance are separate authorized transitions, and an issued snapshot is never
rewritten in place.
"""
