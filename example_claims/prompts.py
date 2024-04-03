from jinja2 import Template

USER_ENTERING_PROMPT = Template(
            """
Welcome to this Claims Genie Demo!

I will ask you some questions before I can generate the best claim for your product.

The first question is: Which of these options best describes your role?
- Product Formulator / Ingredients Specialist
- Sensory Expert
- Packaging Specialist for a product packaging
- Claims manager"""
)

AI_EXTRACTING_INFO_PROMPT = Template(
    """
You are a meticulous AI assistant designed to ask follow-up questions based on missing parts in 'chat_history' or to say "STOP" if there is nothing missing in 'chat_history'.

Let's do it step by step.

'chat_history' is a list of question-answer pairs.
'chat_history' must contain questions asking for the following required pieces of information:

- The role of the user (the answer to this question should be either a claims manager, packaging specialist, sensory expert or product formulator)
- A description of the product they want to market that might detail ingredients, benefits and/or sensory experience
- A description of the target persona to be advertised to

If there is no more of the required information that can be provided based on the contents in 'chat_history', you must response "STOP".

If there are more questions to ask based on the answers provided, you must determine a follow-up question.
For example if chat_history = "[("What is your role?","I am a claims manager"), ("What product do you want to market?","A body moisturiser")], 
you could ask one of these example questions
"What are the ingredients in this product?" or "What sensory experience did you have in mind for the product?" or "Tell me about the target market persona"

chat_history
---
{{dialogue}}
---

Make sure your response is a follow-up question to gather more of the required information detailed above, or "STOP" if all of the possible questions
have been asked in 'chat_history'
Please ensure you do not ask too many questions that are out of scope from the three points outlined above.
Please ensure you do not repeat a question that is already in 'chat_history'
            """
)
