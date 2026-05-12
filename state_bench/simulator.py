"""User simulator — LLM-powered user with task-specific behavior.

The UserSimulator receives an assembled system prompt (personality + task context
+ base rules + task-specific rules) and responds in character.
"""

import json
from typing import Any

from state_bench.client import LLMClient, PooledLLMClient


class UserSimulator:
    """LLM-powered user simulator for multi-turn conversations."""

    def __init__(self, client: LLMClient | PooledLLMClient, system_prompt: str):
        self.client = client
        self.system_prompt = system_prompt

    def respond(self, conversation: list[dict[str, Any]]) -> str:
        """Generate a user response given the conversation history.

        Args:
            conversation: Full conversation history including tool call summaries.

        Returns:
            The simulated user response.
        """
        # Build conversation as a readable text block for the simulator
        lines: list[str] = []
        for msg in conversation:
            role = msg["role"].upper()
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls")

            if role == "ASSISTANT" and tool_calls:
                tc_summary = "\n".join(
                    f"[Called {tc['name']}({json.dumps(tc.get('arguments', {}), ensure_ascii=False)[:200]})]"
                    for tc in tool_calls
                )
                content = f"{tc_summary}\n{content}" if content else tc_summary

            if content:
                lines.append(f"{role}: {content}")

        conversation_text = "\n\n".join(lines)

        instruction = (
            f"CONVERSATION SO FAR:\n{conversation_text}\n\n"
            "Respond as the customer based on the conversation and your rules above.\n"
            "YOUR RESPONSE:"
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": instruction},
        ]

        return self.client.complete_chat(messages=messages).strip()
