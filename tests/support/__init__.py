"""Shared test doubles for the OpenTorus suite.

Importable as ``from support.providers import ScriptedProvider`` because pytest puts
``tests/`` (the directory holding ``conftest.py``) on ``sys.path``. Nothing in here is
shipped: production code under mock always uses ``MockProvider`` via ``get_provider``.
"""
