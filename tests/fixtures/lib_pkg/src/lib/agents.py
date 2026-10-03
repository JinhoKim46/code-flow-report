from lib.models import Model

__all__ = ["Agent"]


class Base:
    def __init__(self, model: Model):
        self.model = model

    def run(self, task):
        return self.step(task)

    def step(self, task):
        raise NotImplementedError


class Agent(Base):
    def step(self, task):
        return self.model.generate([task])
