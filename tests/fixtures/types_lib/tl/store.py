from dataclasses import dataclass
from typing import Optional


class Store:
    def save(self):
        return 1

    def only_here_xyz(self):
        return 2


class Child(Store):
    def save(self):
        return super().save()


@dataclass
class Box:
    store: Store


def make() -> Store:
    return Store()


def build():
    return Store()


def maybe(s: Optional[Store]):
    return s.save()


def quoted(s: "Store"):
    return s.save()
