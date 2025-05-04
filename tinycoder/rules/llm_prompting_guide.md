# Guide to Writing Effective LLM Prompts

Get clearer, more reliable answers from Large Language Models (LLMs) by following these best practices:

## 1. Be Clear, Specific, and Contextual

*   **State the Goal Clearly:** Explain precisely what you want the LLM to do.
*   **Provide Context:** Tell the LLM *why* you need the output (e.g., audience, purpose). This helps tailor the response.
*   **Lead with the Ask:** Put your main instruction first. For long prompts, consider repeating the core task at the end (e.g., `REMEMBER: Summarize the key points`).
*   **Define the Output Format:** Specify exactly how you want the response structured (e.g., "5 bullet points", "JSON format", "professional tone").

## 2. Structure Your Prompt Logically

*   **Use Sections:** Organize your prompt with clear headings or sections (e.g., Instructions, Examples, Data).
*   **Use Delimiters:** Use simple separators like blank lines, Markdown headers (`#`, `##`), or basic XML-style tags (`<instructions>`, `<example>`) to distinguish different parts of your prompt.
*   **Standard Order:** A good flow is often: Role -> Instructions -> Examples -> Context/Data -> Final Question/Task.

## 3. Provide Examples (Few-Shot Prompting)

*   **Show, Don't Just Tell:** Include 1-5 clear examples of the input and the desired output. This is very effective for specific formats or complex tasks.
*   **Vary Examples:** Ensure your examples cover different scenarios or potential edge cases.

## 4. Guide the Thinking Process

*   **Assign a Role:** Define a persona for the LLM (e.g., "You are a helpful editor," "Act as a data analyst"). This shapes its tone and focus.
*   **Encourage Step-by-Step Thinking:** For complex problems, ask the model to "Think step-by-step" or "Outline your plan" before generating the final answer.
*   **Request Reasoning:** If you need to understand *how* the LLM reached its answer, ask it to include a brief explanation.

## 5. Manage Context and Constraints

*   **Include Relevant Information:** Provide necessary documents or data directly within the prompt, clearly marked.
*   **Limit Knowledge Source:** If needed, instruct the LLM to *only* use the provided information ("Based solely on the text below...").
*   **Set Boundaries:** Tell the model when to stop (e.g., "Generate 3 options") or how to handle specific conditions (e.g., "If the answer is unknown, state that").

## 6. Iterate and Refine

*   **Test Your Prompts:** Prompting often requires experimentation. Check the results and adjust your instructions or examples accordingly.
*   **Know Your Model:** Different LLMs have different strengths. Adapt your prompting style based on the model you are using (e.g., more explicit steps for some, higher-level goals for others). Refer to specific model documentation for best practices.

Following these guidelines will help you create prompts that lead to more accurate, consistent, and useful LLM responses.