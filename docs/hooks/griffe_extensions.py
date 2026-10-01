"""Griffe extensions used by mkdocstrings when building the lcls2 docs.

Both run once per loaded package (``on_package``), after griffe has parsed
the source and expanded the wildcard imports it could. They only change what
the API pages show; they never import or modify the code.
"""

from griffe import Extension


class DropUnresolvedWildcards(Extension):
    """Remove wildcard imports that griffe could not expand.

    Some modules do ``from psdaq.seq.seq import *``, but ``psdaq/psdaq/seq``
    has no ``__init__.py``, so griffe cannot find ``psdaq.seq.seq``. The
    unexpanded wildcard import is then re-exported by other wildcard imports
    (for example ``psdaq.pyxpm.pykcuxpm`` imports ``*`` from
    ``psdaq.pyxpm.pvctrls``), and griffe 2.x crashes with
    ``AliasResolutionError`` while resolving aliases. Dropping these
    placeholders avoids the crash; documented objects are not touched.
    """

    def on_package(self, *, pkg, loader, **kwargs):
        self._clean_module(pkg, loader)

    def _clean_module(self, module, loader):
        for name, member in list(module.members.items()):
            if member.is_alias:
                if member.wildcard and not self._points_to_loaded_module(member, loader):
                    module.del_member(name)
            elif member.is_module:
                self._clean_module(member, loader)

    @staticmethod
    def _points_to_loaded_module(alias, loader):
        try:
            target = loader.modules_collection.get_member(alias.wildcard)
        except KeyError:
            return False
        return (not target.is_alias) and target.is_module


class DropUndocumentedAttributes(Extension):
    """Hide module and class attributes that have no docstring.

    The API pages show every function, class and method, documented or not
    (``show_if_no_docstring: true``), so that signatures are always visible.
    Without this extension they would also list every undocumented
    ``self.x = ...`` assignment, which for classes such as
    ``psdaq.control.control.CollectionManager`` means dozens of entries
    with no information.
    """

    def on_package(self, *, pkg, loader, **kwargs):
        self._clean(pkg)

    def _clean(self, obj):
        for name, member in list(obj.members.items()):
            if member.is_alias:
                continue
            if member.is_attribute and not member.docstring:
                obj.del_member(name)
            elif member.is_module or member.is_class:
                self._clean(member)
