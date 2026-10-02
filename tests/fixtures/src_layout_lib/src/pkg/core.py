from . import util


class Engine:
    def start(self):
        return self.step()

    def step(self):
        return util.helper(1)


def run(x):
    return Engine().start() + util.helper(x)
