from langchain_core.messages import HumanMessage


def ask(llm, question: str):
    return llm.invoke([HumanMessage(content=question)])
