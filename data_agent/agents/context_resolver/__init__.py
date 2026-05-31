"""Entity index and anaphora resolution (ContextResolver)."""

from data_agent.agents.context_resolver.anaphora_resolver import AnaphoraResolverAgent
from data_agent.agents.context_resolver.entity_index import EntityIndex
from data_agent.agents.context_resolver.schemas import AnaphoraRecord

__all__ = ["AnaphoraRecord", "AnaphoraResolverAgent", "EntityIndex"]
