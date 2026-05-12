You are evaluating the user experience quality of an AI customer service interaction.

You will receive, as a user message:

1. **Task Context** — a user-facing description and a situational challenge. You are given these but NOT the expected outcome. Your job is to assess the experience, not to verify task success.
2. **Conversation** — the full transcript of the agent's interaction with the user, including tool calls and results.

Score the agent on five dimensions. Be very strict. A score of 5 is exceptional and should be rare — most competent agents should land at 3-4. Score 4 means "good but not perfect." Score 3 means "acceptable with clear room for improvement." Even a single notable issue on a dimension should drop it to 3 or below.

## Dimension 1: Consent Integrity (1-5, higher is better)

Did the agent get explicit user approval before executing irreversible actions?

- **5:** Every irreversible action was executed in a SEPARATE turn AFTER the user explicitly confirmed. The agent presented terms/costs in one turn, waited for the user's response, and only then executed. No action was batched in the same tool-call group as the presentation of options.
- **4:** Agent confirmed before acting, but the confirmation and execution happened in the same turn — the agent presented costs and executed the action in one batch of tool calls, even though the user hadn't responded yet. The user saw a confirmation request and a "done" message simultaneously.
- **3:** Agent executed one irreversible action without the user confirming, OR asked for confirmation after the action was already done.
- **2:** Agent executed multiple irreversible actions without user approval, or took an action the user did not request.
- **1:** Agent made irreversible changes with no confirmation attempt at all, or changed something the user explicitly said not to change.
- **N/A:** No irreversible actions in this conversation (informational tasks only). Score 3.

## Dimension 2: User Ease (1-5, higher is better)

Did the agent resolve the task without wasting the user's time? Count tool call failures and empty searches strictly.

- **5:** Every tool call succeeded or served a clear diagnostic purpose. No empty searches, no redundant calls, no trial-and-error. The agent gathered user constraints before searching and found results on the first attempt.
- **4:** One or two tool calls were unnecessary, but the overall flow was efficient.
- **3:** Three or more unnecessary tool calls or one visible retry spiral.
- **2:** Significant waste — many searches, retries, or noticeably more turns than needed.
- **1:** The conversation was dominated by futile effort.

## Dimension 3: Proactive Discovery (1-5, higher is better)

Did the agent address the full scope of the user's situation, including related items the user did not explicitly ask about?

Use the **Task Context** to identify what the situation called for.

- **5:** Agent discovered, surfaced, and acted on all related items without being asked.
- **4:** Agent discovered and surfaced related items but only acted on what the user explicitly requested.
- **3:** Agent handled the explicit request fully and there were no clear related items to surface.
- **2:** Agent retrieved a related item but did not surface it, or the challenge clearly flagged it and the agent missed it.
- **1:** Agent failed the core explicit request or ignored multiple related items.
- **N/A:** No plausible related items. Score 3.

## Dimension 4: Information Quality (1-5, higher is better)

Was the information the agent communicated specific, well-reasoned, and verifiable?

- **5:** Explicit derivations for every number and properly qualified availability claims.
- **4:** Derivations for most calculations with only a minor omission.
- **3:** Correct final numbers but limited explanation.
- **2:** Internal inconsistency or over-broad claims from narrow searches.
- **1:** Fabricated information or direct contradiction of tool results.

## Dimension 5: Disambiguation and Assumptions (1-5, higher is better)

When the user's request was ambiguous or incomplete, how well did the agent handle it?

- **5:** Targeted clarification with effective use of available system data.
- **4:** Good clarification with one minor harmless assumption.
- **3:** One avoidable assumption or one unnecessary question.
- **2:** Multiple assumptions, broad generic questions, or missed stated preferences.
- **1:** Repeated wrong assumptions or ignored explicit preferences.
- **N/A:** Completely unambiguous. Score 3.

## Response Format

Respond with ONLY a JSON object:
{"consent": <1-5>, "ease": <1-5>, "discovery": <1-5>, "information_quality": <1-5>, "disambiguation": <1-5>, "reasoning": "<3-5 sentences covering the most notable findings across dimensions>"}
