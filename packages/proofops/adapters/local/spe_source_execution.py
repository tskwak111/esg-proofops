"""Private, read-scoped inputs for the unchanged source proof functions.

A scope owns one original PDF and immutable graph projections. Source/ref/tenant,
OCR-ledger and complete nested-receipt checks still execute at every call. No
shared module or persistent artifact is patched, and no verdict is cached.
"""

import io
from copy import deepcopy
from dataclasses import asdict, fields, is_dataclass
from importlib.metadata import version
from types import CellType, FunctionType, MethodType, ModuleType, SimpleNamespace

import pdfplumber

from proofops.adapters.local.s5_policy_evaluation import _BUILDERS
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.domain.provenance import canonical_hash


class Evaluation:
    """One policy DAG evaluation; each later boundary starts with live identities."""

    def __init__(self):
        self.values, self.functions, self.versions = {}, {}, {}

    def package_version(self, name):
        if name not in self.versions:
            self.versions[name] = version(name)
        return self.versions[name]

    def bind(self, original):
        if original in self.functions:
            return self.functions[original]

        def invoke():
            if original not in self.values:
                self.values[original] = cloned()
            return deepcopy(self.values[original])

        self.functions[original] = invoke
        evaluation = self

        class ModuleView:
            def __init__(self, module):
                self.module = module

            def __getattr__(self, name):
                value = getattr(self.module, name)
                if name in _BUILDERS and isinstance(value, FunctionType):
                    return evaluation.bind(value)
                return value

        namespace = original.__globals__.copy()
        for name, value in namespace.copy().items():
            if value is version:
                namespace[name] = self.package_version
            elif isinstance(value, ModuleType) and value.__name__.startswith("proofops."):
                namespace[name] = ModuleView(value)
            elif isinstance(value, FunctionType) and value.__name__ in _BUILDERS:
                namespace[name] = self.bind(value)
        cloned = FunctionType(
            original.__code__,
            namespace,
            original.__name__,
            original.__defaults__,
            original.__closure__,
        )
        cloned.__kwdefaults__ = original.__kwdefaults__
        return invoke


def evaluate(function):
    return Evaluation().bind(function)()


def _readonly(*args, **kwargs):
    raise TypeError("SPE_IMMUTABLE_GRAPH")


class _FrozenDict(dict):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _readonly

    def __deepcopy__(self, memo):
        return self


class _FrozenList(list):
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = _readonly
    reverse = sort = __iadd__ = __imul__ = _readonly

    def __deepcopy__(self, memo):
        return self


def _freeze(value):
    if isinstance(value, dict):
        return _FrozenDict((k, _freeze(v)) for k, v in value.items())
    if isinstance(value, list):
        return _FrozenList(_freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_freeze(v) for v in value)
    return value


def _immutable(value, seen):
    if type(value) in (str, int, float, bool, bytes, type(None)):
        return True
    if id(value) in seen:
        return True
    seen.add(id(value))
    if type(value) is tuple:
        return all(_immutable(v, seen) for v in value)
    if is_dataclass(value) and value.__dataclass_params__.frozen:
        return all(_immutable(getattr(value, f.name), seen) for f in fields(value))
    return False


class _BorrowedPDF:
    def __init__(self, document):
        self.document = document

    def __getattr__(self, name):
        return getattr(self.document, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def close(self):
        pass  # The owning scope closes the real PDF, including all parsed pages.


class SourceScope:
    def __init__(self, graph, source):
        self.graph, self.source = graph, source
        self.document = None
        self.graphs = {}
        self.boxes = {}
        self.box_readers = {}
        self.origins = {}
        self.origin_readers = {}
        self.policies = Evaluation()
        self.functions, self.namespaces, self.modules = {}, {}, {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        if self.document is not None:
            self.document.close()
            self.document = None
        self.graphs.clear()
        self.boxes.clear()
        self.origins.clear()

    def origin_reader(self, original):
        """Reuse raw spacing origins only on pages owned by this original PDF."""
        if original in self.origin_readers:
            return self.origin_readers[original]

        def read(page):
            if page.pdf is not self.document or self.document is None:
                return original(page)
            key = (original, id(page))
            if key not in self.origins:
                result = original(page)
                if len(self.origins) >= 32:
                    return result
                self.origins[key] = (page, result)
            # Callers may alter their mapping, never the retained raw origins.
            return self.origins[key][1].copy()

        self.origin_readers[original] = read
        return read

    def box_reader(self, original):
        """Project immutable candidate geometry once; keep all layout checks."""
        if original in self.box_readers:
            return self.box_readers[original]

        def read(block):
            key = (original, id(block))
            cached = self.boxes.get(key)
            if cached is not None and cached[0] is block:
                return cached[1]
            result = original(block)
            if len(self.boxes) < 4096 and _immutable(block, set()):
                self.boxes[key] = (block, result)
            return result

        self.box_readers[original] = read
        return read

    def open_pdf(self, stream, *args, **kwargs):
        if self.closed:
            raise RuntimeError("SPE_SOURCE_SCOPE_CLOSED")
        # Only identical in-memory originals with exactly the default options
        # share parsing. Files, passwords and alternate configurations retain
        # the original reader path and errors.
        if (
            type(self.source) is bytes
            and not args
            and not kwargs
            and isinstance(stream, io.BytesIO)
            and (stream.getvalue() == self.source)
        ):
            if self.document is None:
                self.document = pdfplumber.open(io.BytesIO(self.source))
            return _BorrowedPDF(self.document)
        return pdfplumber.open(stream, *args, **kwargs)

    def asdict(self, value):
        if type(value) is CanonicalDocumentGraph:
            cached = self.graphs.get(id(value))
            if cached is not None and cached[0] is value:
                return cached[1]
            if len(self.graphs) < 4 and _immutable(value, set()):
                data = _freeze(asdict(value))
                self.graphs[id(value)] = (value, data, canonical_hash(data))
                return data
        return asdict(value)

    def canonical_hash(self, value):
        for _, data, digest in self.graphs.values():
            if value is data:
                return digest
        return canonical_hash(value)

    def module(self, original):
        if original in self.modules:
            return self.modules[original]
        scope = self

        class ModuleView:
            def __getattr__(self, name):
                if original is pdfplumber and name == "open":
                    return scope.open_pdf
                return scope.value(getattr(original, name))

        proxy = ModuleView()
        self.modules[original] = proxy
        return proxy

    def value(self, value):
        if value is asdict:
            return self.asdict
        if value is canonical_hash:
            return self.canonical_hash
        if value is version:
            return self.policies.package_version
        if isinstance(value, ModuleType) and (
            value is pdfplumber or value.__name__.startswith("proofops.adapters.local.")
        ):
            return self.module(value)
        if isinstance(value, MethodType):
            return MethodType(self.function(value.__func__), value.__self__)
        if isinstance(value, FunctionType) and value.__module__.startswith(
            "proofops.adapters.local."
        ):
            if value.__name__ == "_spacing_origins" and value.__code__.co_filename.endswith(
                "/native_glyph_geometry.py"
            ):
                return self.origin_reader(value)
            if value.__name__ == "_selected_box" and value.__code__.co_filename.endswith(
                "/table_span_source_verification.py"
            ):
                return self.box_reader(value)
            if value.__name__ in _BUILDERS:
                return self.policies.bind(value)
            if value.__name__ == "_exec_private":

                def private(*args, **kwargs):
                    module = value(*args, **kwargs)
                    # _exec_private returns a new, unregistered module owned by
                    # this invocation. Later reader assignments must remain live.
                    self.namespace(module.__dict__, private=True)
                    return module

                return private
            return self.function(value)
        if isinstance(value, SimpleNamespace):
            return SimpleNamespace(**{k: self.value(v) for k, v in vars(value).items()})
        return value

    def namespace(self, original, *, private=False):
        identity = id(original)
        if identity in self.namespaces:
            return self.namespaces[identity]
        namespace = original if private else original.copy()
        self.namespaces[identity] = namespace
        for name, value in list(namespace.items()):
            namespace[name] = self.value(value)
        return namespace

    def function(self, original, **bindings):
        if not bindings and original in self.functions:
            return self.functions[original]
        identity = id(original.__globals__)
        prepare = identity not in self.namespaces
        if prepare:
            self.namespaces[identity] = original.__globals__.copy()
        target = self.namespaces[identity]
        namespace = target | bindings if bindings else target
        cells = tuple(CellType() for _ in original.__closure__) if original.__closure__ else None
        cloned = FunctionType(
            original.__code__, namespace, original.__name__, original.__defaults__, cells
        )
        # Recursive helper references receive this exact function and namespace,
        # never a temporary function with empty globals.
        if not bindings:
            self.functions[original] = cloned
        if prepare:
            for name, value in list(target.items()):
                target[name] = self.value(value)
            if bindings:
                namespace.update(target)
                namespace.update(bindings)
        cloned.__defaults__ = (
            tuple(self.value(v) for v in original.__defaults__)
            if (original.__defaults__ is not None)
            else None
        )
        cloned.__kwdefaults__ = (
            {k: self.value(v) for k, v in original.__kwdefaults__.items()}
            if (original.__kwdefaults__ is not None)
            else None
        )
        if cells:
            for new, old in zip(cells, original.__closure__, strict=True):
                new.cell_contents = self.value(old.cell_contents)
        return cloned

    def bind_reader(self, reader):
        instance = reader
        while True:
            for name in (
                "attest_claim_spans",
                "recompute_claim_receipt",
                "_native_receipt",
                "_finish",
                "_modules",
                "_claim_receipt",
                "_identity",
                "_receipt",
            ):
                existing = instance.__dict__.get(name)
                if isinstance(existing, MethodType):
                    setattr(instance, name, MethodType(self.function(existing.__func__), instance))
                    continue
                if isinstance(existing, FunctionType):
                    # FXH/S5 install a closure here that prepares the private
                    # reader modules. Preserve that binding and its snapshots.
                    setattr(instance, name, self.function(existing))
                    continue
                parent = None
                for cls in reversed(type(instance).__mro__):
                    original = cls.__dict__.get(name)
                    if not isinstance(original, FunctionType):
                        continue
                    bindings = (
                        {}
                        if parent is None
                        else {
                            "super": lambda prior=parent, method=name: SimpleNamespace(
                                **{method: prior}
                            )
                        }
                    )
                    parent = MethodType(self.function(original, **bindings), instance)
                if parent is not None:
                    setattr(instance, name, parent)
            child = instance.__dict__.get("previous", instance.__dict__.get("reader"))
            if child is None:
                break
            instance = child
