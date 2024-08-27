from dependency_injector import containers, providers

from ai_state_machine.invoker import VerbatimInvoker, AzureOpenAIChatInvoker, \
    AzureOpenAIChatJSONInvoker, InvokerFactory, WeaviateSimilaritySearchInvoker
from ai_state_machine.invoker.api import APIInvoker
from ai_state_machine.invoker.neo4j import Neo4jInvoker


class GenieFlowInvokerContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    builtin_registry = providers.Dict(
        verbatim=providers.Object(VerbatimInvoker),
        azure_openai_chat=providers.Object(AzureOpenAIChatInvoker),
        azure_openai_chat_json=providers.Object(AzureOpenAIChatJSONInvoker),
        weaviate_similarity=providers.Object(WeaviateSimilaritySearchInvoker),
        api=providers.Object(APIInvoker),
        neo4j=providers.Object(Neo4jInvoker),
    )

    invoker_factory = providers.Factory(
        InvokerFactory,
        config=config,
        builtin_registry=builtin_registry,
    )
