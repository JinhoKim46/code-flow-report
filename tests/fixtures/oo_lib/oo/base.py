import argparse


class Parser(argparse.ArgumentParser):
    """A library subclass: its inherited methods live in argparse."""


class Store:
    def save(self):
        return 1
