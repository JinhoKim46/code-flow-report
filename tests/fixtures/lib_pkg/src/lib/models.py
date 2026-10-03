from openai import OpenAI


class Model:
    def generate(self, messages):
        raise NotImplementedError


class ApiModel(Model):
    pass


class OpenAIModel(ApiModel):
    def __init__(self):
        self.client = OpenAI()

    def generate(self, messages):
        return self.retry(self.client.chat.completions.create, messages=messages)

    def retry(self, fn, **kwargs):
        return fn(**kwargs)
