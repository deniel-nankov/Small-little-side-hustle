"""Runnable end-to-end pipelines composing the layers (data → signal → validation).

Each pipeline is an importable, unit-tested function; ``scripts/`` holds the thin CLI
wrappers. Pipelines never bypass the guards: data enters through a
:class:`~src.utils.pit.PITDataSource`, decisions are audit-logged, artifacts get
SHA-256 sidecars.
"""
