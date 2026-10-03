from dataclasses import dataclass
from typing import Callable

from ai.client import LLMClient


@dataclass
class Deps:
    make_llm: Callable[[int], LLMClient]
