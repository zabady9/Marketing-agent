from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.content_agent import ContentAgent
from app.agents.critic_agent import CriticAgent
from app.agents.schemas import ContentIdea, ContentOutput, StrategyOutput
from app.agents.strategy_agent import StrategyAgent
from app.services import event_bus


class GraphState(TypedDict):
    brand_profile: dict
    goal: str | None
    ideas: list[dict]            # ContentIdea model_dump() dicts
    current_idx: int             # index of the idea currently being worked on
    revision_count: int          # reset to 0 each time we start a new idea; max 1
    current_content: dict | None # ContentOutput model_dump() dict
    finished_posts: list[dict]   # accumulated results (ContentOutput + idea metadata)
    action_logs: list[dict]      # accumulated log entries; written to DB by run_generation
    workspace_id: str
    plan_id: str


_strategy_agent = StrategyAgent()
_content_agent = ContentAgent()
_critic_agent = CriticAgent()


async def strategy_node(state: GraphState) -> dict:
    plan_id = state["plan_id"]
    brand_profile = state["brand_profile"].copy()  # don't mutate shared state dict
    goal = state["goal"]

    # Best-effort: augment the brand profile with relevant knowledge chunks.
    # A failure here must never block generation.
    try:
        from app.database import AsyncSessionLocal
        from app.services.knowledge_search import search_knowledge

        query = f"{brand_profile.get('brand_name', '')} {goal or ''}".strip()
        if query:
            async with AsyncSessionLocal() as db:
                chunks = await search_knowledge(query, state["workspace_id"], db, k=5)
            if chunks:
                brand_profile["knowledge_context"] = "\n\n---\n\n".join(
                    c.content for c in chunks
                )
    except Exception:
        pass  # knowledge search is best-effort

    await event_bus.emit(plan_id, {"type": "status", "message": "Generating content strategy…"})

    output: StrategyOutput = await _strategy_agent.generate(brand_profile, goal)
    ideas = [idea.model_dump() for idea in output.ideas]

    await event_bus.emit(plan_id, {
        "type": "strategy_done",
        "ideas": [{"day": i["day"], "theme": i["theme"], "format": i["format"]} for i in ideas],
    })

    log = {
        "actor": "strategy_node",
        "action": "generate_ideas",
        "payload": {"goal": goal},
        "result": {"idea_count": len(ideas)},
    }
    return {
        "ideas": ideas,
        "current_idx": 0,
        "revision_count": 0,
        "action_logs": state.get("action_logs", []) + [log],
    }


async def content_node(state: GraphState) -> dict:
    plan_id = state["plan_id"]
    idx = state["current_idx"]
    idea_dict = state["ideas"][idx]
    idea = ContentIdea(**idea_dict)
    brand_profile = state["brand_profile"]

    revision_hint: str | None = None
    if state["revision_count"] > 0 and state.get("current_content"):
        revision_hint = state["current_content"].get("content")

    label = "Rewriting" if revision_hint else "Writing"
    await event_bus.emit(plan_id, {
        "type": "post_start",
        "day": idea.day,
        "theme": idea.theme,
        "format": idea.format,
        "message": f"{label} Day {idea.day}: {idea.theme}…",
    })

    output: ContentOutput = await _content_agent.write(idea, brand_profile, revision_hint)
    content_dict = output.model_dump()

    await event_bus.emit(plan_id, {
        "type": "post_written",
        "day": idea.day,
        "content": output.content,
        "hashtags": output.hashtags,
        "suggested_time": output.suggested_time,
    })

    log = {
        "actor": "content_node",
        "action": "write_post",
        "payload": {"idea": idea_dict, "revision": state["revision_count"]},
        "result": {"content_length": len(output.content)},
    }
    return {
        "current_content": content_dict,
        "action_logs": state.get("action_logs", []) + [log],
    }


async def critic_node(state: GraphState) -> dict:
    plan_id = state["plan_id"]
    content_dict = state["current_content"]
    content = ContentOutput(**content_dict)
    brand_profile = state["brand_profile"]
    idx = state["current_idx"]
    idea_dict = state["ideas"][idx]

    await event_bus.emit(plan_id, {
        "type": "critic_start",
        "day": idea_dict["day"],
        "message": f"Reviewing Day {idea_dict['day']}…",
    })

    from app.agents.schemas import CriticOutput
    output: CriticOutput = await _critic_agent.review(content, brand_profile)

    log = {
        "actor": "critic_node",
        "action": "review_post",
        "payload": {"approved": output.approved, "issues": output.issues},
        "result": {"fixed_body_provided": output.fixed_body is not None},
    }

    updates: dict = {"action_logs": state.get("action_logs", []) + [log]}

    if not output.approved and state["revision_count"] == 0 and output.fixed_body:
        await event_bus.emit(plan_id, {
            "type": "critic_revision",
            "day": idea_dict["day"],
            "issues": output.issues,
            "message": f"Day {idea_dict['day']} needs revision — rewriting…",
        })
        updates["current_content"] = {**content_dict, "content": output.fixed_body}
        updates["revision_count"] = 1
    else:
        finished = {**content_dict, **idea_dict}
        updates["finished_posts"] = state.get("finished_posts", []) + [finished]
        await event_bus.emit(plan_id, {
            "type": "post_approved",
            "day": idea_dict["day"],
            "theme": idea_dict["theme"],
            "content": content_dict["content"],
            "hashtags": content_dict.get("hashtags", []),
            "suggested_time": content_dict.get("suggested_time", ""),
            "message": f"Day {idea_dict['day']} approved ✓",
        })

    return updates


def advance_node(state: GraphState) -> dict:
    return {
        "current_idx": state["current_idx"] + 1,
        "revision_count": 0,
        "current_content": None,
    }


def _after_critic(state: GraphState) -> str:
    """Route: re-run content if revision needed, else advance."""
    if state["revision_count"] == 1 and len(state.get("finished_posts", [])) == state["current_idx"]:
        # critic just set revision_count=1 and did NOT append to finished_posts
        return "content"
    return "advance"


def _after_advance(state: GraphState) -> str:
    """Route: next idea or end."""
    if state["current_idx"] < len(state.get("ideas", [])):
        return "content"
    return END


def build_graph(checkpointer=None):
    builder = StateGraph(GraphState)

    builder.add_node("strategy", strategy_node)
    builder.add_node("content", content_node)
    builder.add_node("critic", critic_node)
    builder.add_node("advance", advance_node)

    builder.set_entry_point("strategy")
    builder.add_edge("strategy", "content")
    builder.add_edge("content", "critic")
    builder.add_conditional_edges("critic", _after_critic, {"content": "content", "advance": "advance"})
    builder.add_conditional_edges("advance", _after_advance, {"content": "content", END: END})

    return builder.compile(checkpointer=checkpointer or MemorySaver())


generation_graph = build_graph()


def init_graph(checkpointer) -> None:
    """Replace the module-level graph with one using the given checkpointer.

    Called once at startup after AsyncPostgresSaver is ready. generation.py
    reads generation_graph via module-attribute lookup (_graph_mod.generation_graph)
    so it sees the replacement immediately on the next ainvoke call.
    """
    global generation_graph
    generation_graph = build_graph(checkpointer)
