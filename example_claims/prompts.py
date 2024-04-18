from jinja2 import Template

USER_ENTERING_ROLE_PROMPT = Template(
            """
Welcome to this Claims Genie Demo!

I will ask you some questions before I can generate the best claim for your product.

The first question is: Which of these options best describes your role?
- Product Formulator / Ingredients Specialist
- Sensory Expert
- Packaging Specialist for a product packaging
- Claims manager"""
)

AI_EXTRACTING_USER_ROLE = Template(
    """
You are an AI text classifier designed to determine a user role.
You will be given a description of a user role by a user. Your task is to determine what
the user role is that they describe.

The user roles that you can choose from are the following:
- 'product formulator': someone who creates the (often chemical) formulation of a product
- 'ingredients specialist': someone who understands the effects of different ingredients in a product
- 'sensory expert': someone who understands the sensory aspects of a product
- 'packaging specialist': someone who deals with all packaging aspects of a product
- 'claims manager': someone who specialises in the claims that are made about a product

If you can determine the role of the user, make sure that you only output the name of that role.

If you cannot determine the role, say "Your role is undetermined. I need more information",
followed with a simple question, giving examples of the user roles above, for the user to better
understand their task and give a response from which you can determine their role.

Here follows the user input:
{{actor_input}}
    """
)

USE_ENTERING_INITIAL_INFORMATION = Template(
    """
I have determined that your role is '{{user_role}}'.

In order to create new claims for your product, I need some information. Can you please
provider me with a description of the product that you are marketing as well as the target
persona that you want your claim to appeal to? 
    """
)

AI_EXTRACTING_INFO_PROMPT = Template(
    """
You are a meticulous AI assistant designed to ask follow-up questions based on missing parts
in 'chat_history' or to say "STOP" if there is nothing missing in 'chat_history'.

Let's do it step by step.

'chat_history' is a list of statements made by 
'chat_history' must contain questions asking for the following required pieces of information:

- The role of the user (the answer to this question should be either a claims manager, 
  packaging specialist, sensory expert or product formulator)
- A description of the product they want to market that might detail ingredients, 
  benefits and/or sensory experience
- A description of the target persona to be advertised to

If there is no more of the required information that can be provided based on the contents in
'chat_history', you must response "STOP".

If there are more questions to ask based on the answers provided, you must determine a follow-up
question. For example if chat_history = "[("What is your role?","I am a claims manager"), ("What product do you want to market?","A body moisturiser")], 
you could ask one of these example questions
"What are the ingredients in this product?" or "What sensory experience did you have in mind for the product?" or "Tell me about the target market persona"

The user role is: {{user_role}}

chat_history
---
{{chat_history}}
---

Make sure your response is a follow-up question to gather more of the required information detailed above, or "STOP" if all of the possible questions
have been asked in 'chat_history'
Please ensure you do not ask too many questions that are out of scope from the three points outlined above.
Please ensure you do not repeat a question that is already in 'chat_history'
            """
)

AI_EXTRACTING_CATEGORIES_PROMPT = Template(
            """
You are an insightful AI that understands how to find the relevant parts of information from a question-answer dialogue
Your task is to categorise dictionary tuple in 'chat_history' into the four categories outlined below.
Let's do it step by step.

'chat_history' is a dictionary of dictionaries, where each sub-dictionary contains a question and answer.

For question-answer dictionary, categorise the answer component into the following four categories:
- "user_role" =  The role of the user (normally found in the first dictionary)
- "product_description" = A description of the product they want to market that might detail ingredients, benefits and/or sensory experience
- "target_persona" = A description of the target persona to be advertised
- "further_info" = Any further information

You must generate a json object where the keys are each of the categories outlined above, and the values are the parts you have identified
that belong in the respective category. If there are no parts identified, you can write 'N/A'.

chat_history
---
{{chat_history}}

---
Please ensure that your response is a JSON object of categorised information from 'chat_history'.
Here is the JSON schema that you must adhere to:
{
    user_role: < STR: The role of the user (normally found in the first array) >,
    product_description: < STR: A description of the product they want to market that might detail ingredients, benefits and/or sensory experience >,
    target_persona: < STR: A description of the target persona to be advertised >,
    further_info: < STR: Any further information >,
}
            """
)

USER_VIEWING_START_OF_GENERATION = """
I have now received all the information that I need from you. 

Let me categorise this information for you. Hold tight...
"""

USER_VIEWING_CATEGORIES_PROMPT = Template(
    """
I have now found the following information:

Your role is: {{ user_role }}

Your describe the product as: {{ product_description}}

Your target persona is described as: {{ target_persona }}

And I found some further information: {{ further_info }}

I will now conduct some background research on this. Bear with me.
    """
)

AI_CONDUCTING_RESEARCH_PROMPT_INGREDIENTS = Template(
    """   
You are an insightful AI that understands people and marketing.
The task is to generate a statement that advertises a product designed for a target_persona.
Before this task takes place, it's time to step back and answer a few questions. 

'user_information' contains the role of the user, "user_role", a description of the product to be 
marketed, "product_description", the target persona to be marketed to, "target_persona", and any
further information, "further_info".

You must use the information provided below to answer the following question:
1. Would the target persona be interested in knowing about the ingredients of a product?

---
user role: 
{{user_role}}

---
product description:
{{product_description}}

---
target_persona:
{{target_persona}}

---
further_info:
{{further_info}}

---
Your response should be all the answers to these questions with the given information.
Answer the questions in the order they are given in and explain why your answer is the most
appropriate answer for each question.
    """
)

AI_CONDUCTING_RESEARCH_PROMPT_BENEFITS = Template(
    """   
You are an insightful AI that understands people and marketing.
The task is to generate a statement that advertises a product designed for a target_persona.
Before this task takes place, it's time to step back and answer a few questions. 

'user_information' contains the role of the user, "user_role", a description of the product to be 
marketed, "product_description", the target persona to be marketed to, "target_persona", and any
further information, "further_info".

You must use the information provided below to answer the following question:
2. What benefits in the product would the target persona be interested in?

---
user role: 
{{user_role}}

---
product description:
{{product_description}}

---
target_persona:
{{target_persona}}

---
further_info:
{{further_info}}

---
Your response should be all the answers to these questions with the given information.
Answer the questions in the order they are given in and explain why your answer is the most
appropriate answer for each question.
    """
)
AI_CONDUCTING_RESEARCH_PROMPT_SENSORY = Template(
    """   
You are an insightful AI that understands people and marketing.
The task is to generate a statement that advertises a product designed for a target_persona.
Before this task takes place, it's time to step back and answer a few questions. 

'user_information' contains the role of the user, "user_role", a description of the product to be 
marketed, "product_description", the target persona to be marketed to, "target_persona", and any
further information, "further_info".

You must use the information provided below to answer the following question:
3. What sort of sensory experience would the target persona be interested in with the product?

---
user role: 
{{user_role}}

---
product description:
{{product_description}}

---
target_persona:
{{target_persona}}

---
further_info:
{{further_info}}

---
Your response should be all the answers to these questions with the given information.
Answer the questions in the order they are given in and explain why your answer is the most
appropriate answer for each question.
    """
)
AI_CONDUCTING_RESEARCH_PROMPT_MARKETING = Template(
    """   
You are an insightful AI that understands people and marketing.
The task is to generate a statement that advertises a product designed for a target_persona.
Before this task takes place, it's time to step back and answer a few questions. 

'user_information' contains the role of the user, "user_role", a description of the product to be 
marketed, "product_description", the target persona to be marketed to, "target_persona", and any
further information, "further_info".

You must use the information provided below to answer the following question:
4. How would you market the product to the target persona?

---
user role: 
{{user_role}}

---
product description:
{{product_description}}

---
target_persona:
{{target_persona}}

---
further_info:
{{further_info}}

---
Your response should be all the answers to these questions with the given information.
Answer the questions in the order they are given in and explain why your answer is the most
appropriate answer for each question.
    """
)
AI_CONDUCTING_RESEARCH_PROMPT_PACKAGING = Template(
    """   
You are an insightful AI that understands people and marketing.
The task is to generate a statement that advertises a product designed for a target_persona.
Before this task takes place, it's time to step back and answer a few questions. 

'user_information' contains the role of the user, "user_role", a description of the product to be 
marketed, "product_description", the target persona to be marketed to, "target_persona", and any
further information, "further_info".

You must use the information provided below to answer the following question:
5. If the user role is not a packaging specialist, then ignore this question. If the user role is a 
packaging specialist, then what specific recommendations do you have to package the product that 
would appeal to the target persona?

---
user role: 
{{user_role}}

---
product description:
{{product_description}}

---
target_persona:
{{target_persona}}

---
further_info:
{{further_info}}

---
Your response should be all the answers to these questions with the given information.
Answer the questions in the order they are given in and explain why your answer is the most
appropriate answer for each question.
    """
)

USER_VIEWING_BACKGROUND_RESEARCH_PROMPT = Template(
    """
I have now done some background research, and I find the following:

{{ actor_input }}

Now, with all the information that is provided, let me generate three claims for you.
Please hang on.
    """
)

AI_GENERATES_CLAIMS_PROMPT = Template(
    """
You are a creative and persuading AI assistant.
Your task is to generate three effective marketing claims for a product.
These claims should be targeted at a given persona.

Let's do it step by step. 

First read the 'strong claims examples' which gives examples of strong and well-formed claims.
Then read 'background research' which gives some background about how to market the product for the target persona.
Then read the 'persona description' which gives a bio for the target persona.
Then read the 'product information' which gives a description of the product.
Then read any 'further information' that may be given.

Using all this information, generate three new marketing claims for the product that will make the 
product desirable for the target persona.

Provide any other useful information for the user, if any.

If there is any information in question 5 of 'background research', about packaging advice then provide this information too.

Make sure to keep your claims as snappy as the examples, not going into too much detail.

Finally, read your suggested claims and validate these against the 'background research', 
'persona description', the 'product information' and any 'further information', and 
check if your new claims:
- will seem desirable to that persona
- align with the 'product information'
- do not contradict the 'background research'.

Make changes to your claims if any of these validations are invalid.

---
strong claims examples:

- Replenishes 100 percent of daily hydration
- Nourishing vitamins e and c
- Nourishing moisture
- 24-hour hydration
- Luscious hydration
- Locks in moisture
- Super hydrating

---
background research:
{{step_back_research}}

---
persona description:
{{target_persona}}

---
product information:
{{product_description}}

---
further information:
{{further_info}}

---

Your response should be three effective claims of the product tailored for the persona that is a
similar length to the strong claims examples.
    """
)

USER_VIEWS_GENERATED_CLAIMS = Template(
    """
I have now generated the following claims:

{{actor_input}}

This is the end of our chat.
    """
)
