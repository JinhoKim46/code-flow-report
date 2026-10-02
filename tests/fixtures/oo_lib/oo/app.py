import argparse

from oo.base import Parser, Store

parser = Parser()
parser.add_argument("--verbose")


class Service:
    def __init__(self):
        self.store = Store()

    def run(self):
        return self.store.save()


def configure(p: argparse.ArgumentParser):
    p.add_argument("--quiet")
