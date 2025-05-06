import collections

from genie_flow.utils import get_fully_qualified_name_from_class, \
    get_class_from_fully_qualified_name


def test_fqn():
    fqn = get_fully_qualified_name_from_class(collections.OrderedDict())
    assert fqn == "collections.OrderedDict"


def test_cls():
    cls = get_class_from_fully_qualified_name("collections.OrderedDict")

    assert cls == collections.OrderedDict
