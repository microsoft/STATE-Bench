You are evaluating whether a customer service agent satisfied the authored non-state task requirements for a customer-support benchmark task.

## Task Summary
$task_summary

## Authored Task Requirements
$task_requirements

## Instructions

Use the authored `task_requirements` list as the only ground truth for this evaluation.

Each requirement has:
- `id`: stable identifier
- `kind`: either `must` or `must_not`
- `requirement`: the requirement text to check
- `evidence`: where the requirement should be verified, usually conversation or conversation_or_tool_calls

Scoring rules:
- Return `score: 1` only if every requirement passes.
- Return `score: 0` if any requirement fails.
- If evidence is insufficient, mark that requirement as failed rather than guessing.
- Focus only on the non-state task requirements listed above.
- Be strict about wrong denials, omitted disclosures, missing alternatives, and false claims about policy.
- If a requirement contains a specific amount, threshold, timeline, fee, membership rule, or policy condition, treat any mismatch as a failure for that requirement.
- For `must_not` requirements, any clear violation should fail that requirement even if the agent later recovers.

For each authored requirement, return one detail object with:
- `id`
- `passed`: true or false
- `reasoning`: brief evidence-based explanation

## Conversation
$conversation

Respond with ONLY a JSON object in this shape:
{
  "details": [
    {
      "id": "requirement_id",
      "passed": false,
      "reasoning": "Brief evidence-based explanation."
    }
  ]
}
