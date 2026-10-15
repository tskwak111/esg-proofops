"""Evaluate a source-policy DAG once per call, with private function globals.

Historical policy builders repeatedly expand the same predecessor. Cache only
zero-argument policy builders during this evaluation, returning independent
copies. No global module, file or persistent cache is patched. Every subsequent
evaluation reads live code/tool identities again.
"""

from copy import deepcopy
from types import FunctionType, ModuleType

_BUILDERS = frozenset(
    {
        "policy",
        "claim_source_policy",
        "native_policy",
        "reader_policy",
        "table_span_policy",
        "table_policy_sha256",
        "prose_policy",
        "runtime_policy",
    }
)


def evaluate(function):
    values = {}
    functions = {}

    class ModuleView:
        def __init__(self, module):
            self.module = module

        def __getattr__(self, name):
            value = getattr(self.module, name)
            return bind(value) if name in _BUILDERS and isinstance(value, FunctionType) else value

    def bind(original):
        if original in functions:
            return functions[original]

        def invoke():
            if original not in values:
                values[original] = cloned()
            return deepcopy(values[original])

        functions[original] = invoke
        namespace = original.__globals__.copy()
        for name, value in namespace.copy().items():
            if isinstance(value, ModuleType) and value.__name__.startswith("proofops."):
                namespace[name] = ModuleView(value)
            elif isinstance(value, FunctionType) and value.__name__ in _BUILDERS:
                namespace[name] = bind(value)
        cloned = FunctionType(
            original.__code__,
            namespace,
            original.__name__,
            original.__defaults__,
            original.__closure__,
        )
        cloned.__kwdefaults__ = original.__kwdefaults__
        return invoke

    return bind(function)()
