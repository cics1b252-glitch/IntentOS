"""Minimal pytest compatibility shim for standard library unittest execution."""

import sys
import unittest

def fixture(*args, **kwargs):
    def decorator(fn):
        return fn
    if len(args) == 1 and callable(args[0]):
        return args[0]
    return decorator

class Mark:
    def asyncio(self, fn):
        return fn
    def skip(self, reason=""):
        def decorator(fn):
            return fn
        return decorator
    def parametrize(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator
    def __getattr__(self, name):
        def decorator(*args, **kwargs):
            def inner(fn):
                return fn
            if len(args) == 1 and callable(args[0]):
                return args[0]
            return inner
        return decorator

mark = Mark()

class RaisesContext:
    def __init__(self, expected_exception):
        self.expected_exception = expected_exception
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError(f"Expected exception {self.expected_exception} was not raised")
        return issubclass(exc_type, self.expected_exception)

def raises(expected_exception, *args, **kwargs):
    return RaisesContext(expected_exception)
