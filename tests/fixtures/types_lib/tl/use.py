import csv

from tl.store import Box, Store, build, make


def returns():
    a = make()
    b = build()
    return a.save() + b.save()


def field(box: Box):
    return box.store.save()


def takes(x):
    return x.save()


def caller():
    return takes(Store())


def values(data=None):
    d = data or {}
    return d.get("k"), ", ".join(["a", "b"]), "x".upper().strip()


def rows(f):
    for row in csv.reader(f):
        row.count("a")


def guess(obj):
    return obj.only_here_xyz()
