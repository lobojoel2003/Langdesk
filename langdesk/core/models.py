"""Langdesk core has no models of its own.

This module exists so Django sends ``post_migrate`` for the app, which creates the role
groups (see ``apps.py``).
"""
