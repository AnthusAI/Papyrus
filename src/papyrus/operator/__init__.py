"""Operator-facing CLI surface for local pod and cloud backends."""

from .runtime import dispatch_operator_command, is_operator_command

__all__ = ["dispatch_operator_command", "is_operator_command"]
